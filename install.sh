#!/usr/bin/env bash
#
# Install the SoftEther VPN Wrapper: the privileged D-Bus helper (system wide)
# and the graphical client (per desktop user).
#
# Usage:
#   sudo ./install.sh [desktop-user]
#
# If no desktop user is given, the invoking user (SUDO_USER) is used, falling
# back to the first non-root logged-in user.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HELPER_ROOT="/opt/softether-wrapper"
HELPER_VENV="$HELPER_ROOT/venv"
HELPER_LIB="$HELPER_ROOT/lib"

TARGET_USER="${1:-${SUDO_USER:-}}"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Please run as root: sudo $0 [desktop-user]"

command -v python3 >/dev/null || die "python3 is required"
if ! command -v vpncmd >/dev/null; then
  die "vpncmd was not found. Install the SoftEther VPN client package first."
fi

if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
  TARGET_USER="$(loginctl list-users --no-legend 2>/dev/null | awk '$2 != 0 {print $2; exit}')" || true
fi

# ---------------------------------------------------------------------------
# Privileged helper
# ---------------------------------------------------------------------------
log "Installing the D-Bus helper under $HELPER_ROOT"
install -d -m 0755 "$HELPER_ROOT"
python3 -m venv "$HELPER_VENV"
"$HELPER_VENV/bin/pip" install --upgrade pip >/dev/null
"$HELPER_VENV/bin/pip" install "dbus-next>=0.2.3" >/dev/null

install -d -m 0755 "$HELPER_LIB"
rm -rf "$HELPER_LIB/softether_wrapper_helper"
cp -r "$REPO_DIR/helper/softether_wrapper_helper" "$HELPER_LIB/"

log "Installing systemd / D-Bus / polkit integration"
install -m 0644 "$REPO_DIR/packaging/systemd/softether-wrapper-helper.service" \
  /etc/systemd/system/softether-wrapper-helper.service
install -m 0644 "$REPO_DIR/packaging/dbus/org.softether.Wrapper.conf" \
  /usr/share/dbus-1/system.d/org.softether.Wrapper.conf
install -m 0644 "$REPO_DIR/packaging/polkit/org.softether.wrapper.policy" \
  /usr/share/polkit-1/actions/org.softether.wrapper.policy

systemctl daemon-reload
systemctl enable --now softether-wrapper-helper.service
systemctl reload dbus.service 2>/dev/null || warn "could not reload dbus.service (a reboot recreates the bus policy)"

# ---------------------------------------------------------------------------
# Graphical client (per user)
# ---------------------------------------------------------------------------
if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
  warn "No desktop user found; skipping the graphical client install."
  warn "Re-run: sudo $0 <desktop-user>"
  exit 0
fi

log "Installing the graphical client for user '$TARGET_USER'"
USER_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
USER_GROUP="$(id -gn "$TARGET_USER")"
APP_ROOT="$USER_HOME/.local/share/softether-wrapper"
APP_VENV="$APP_ROOT/venv"

install -d -m 0755 -o "$TARGET_USER" -g "$USER_GROUP" "$APP_ROOT"
# A private venv is used so the GUI never depends on the host Python packages.
sudo -u "$TARGET_USER" python3 -m venv "$APP_VENV"
sudo -u "$TARGET_USER" "$APP_VENV/bin/pip" install --upgrade pip >/dev/null
sudo -u "$TARGET_USER" "$APP_VENV/bin/pip" install \
  "PySide6-Essentials>=6.5" "dbus-next>=0.2.3" "qasync>=0.27"
sudo -u "$TARGET_USER" "$APP_VENV/bin/pip" install --no-deps "$REPO_DIR" >/dev/null

log "Installing desktop integration for '$TARGET_USER'"
install -d -m 0755 -o "$TARGET_USER" -g "$USER_GROUP" \
  "$USER_HOME/.local/bin" \
  "$USER_HOME/.local/share/applications" \
  "$USER_HOME/.local/share/icons/hicolor/scalable/apps"

cat > "$USER_HOME/.local/bin/softether-wrapper" <<EOF
#!/usr/bin/env sh
exec "$APP_VENV/bin/softether-wrapper" "\$@"
EOF
chmod 0755 "$USER_HOME/.local/bin/softether-wrapper"
chown "$TARGET_USER:$USER_GROUP" "$USER_HOME/.local/bin/softether-wrapper"

install -m 0644 -o "$TARGET_USER" -g "$USER_GROUP" \
  "$REPO_DIR/packaging/softether-wrapper.desktop" \
  "$USER_HOME/.local/share/applications/softether-wrapper.desktop"
install -m 0644 -o "$TARGET_USER" -g "$USER_GROUP" \
  "$REPO_DIR/src/softether_wrapper/resources/icons/state-connected.svg" \
  "$USER_HOME/.local/share/icons/hicolor/scalable/apps/softether-wrapper.svg"

cat <<EOF

Installed.

  Helper : systemctl status softether-wrapper-helper.service
  GUI    : $USER_HOME/.local/bin/softether-wrapper

Make sure "$USER_HOME/.local/bin" is on PATH, then launch the app from the
application menu or run:

  $USER_HOME/.local/bin/softether-wrapper

EOF
