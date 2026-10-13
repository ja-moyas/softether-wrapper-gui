#!/usr/bin/env bash
#
# Remove the SoftEther VPN Wrapper (helper and graphical client).
#
# Usage:
#   sudo ./uninstall.sh [desktop-user]
set -euo pipefail

HELPER_ROOT="/opt/softether-wrapper"
TARGET_USER="${1:-${SUDO_USER:-}}"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Please run as root: sudo $0 [desktop-user]"

if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
  TARGET_USER="$(loginctl list-users --no-legend 2>/dev/null | awk '$2 != 0 {print $2; exit}')" || true
fi

log "Stopping and disabling the helper service"
systemctl disable --now softether-wrapper-helper.service 2>/dev/null || true
rm -f /etc/systemd/system/softether-wrapper-helper.service
systemctl daemon-reload

log "Removing system integration files"
rm -f /usr/share/dbus-1/system.d/org.softether.Wrapper.conf
rm -f /usr/share/polkit-1/actions/org.softether.wrapper.policy
rm -rf "$HELPER_ROOT"
systemctl reload dbus.service 2>/dev/null || true

if [[ -n "$TARGET_USER" && "$TARGET_USER" != "root" ]]; then
  USER_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
  log "Removing the graphical client for '$TARGET_USER'"
  rm -rf "$USER_HOME/.local/share/softether-wrapper"
  rm -f "$USER_HOME/.local/bin/softether-wrapper"
  rm -f "$USER_HOME/.local/share/applications/softether-wrapper.desktop"
  rm -f "$USER_HOME/.local/share/icons/hicolor/scalable/apps/softether-wrapper.svg"
  rm -f "$USER_HOME/.config/autostart/softether-wrapper.desktop"
fi

log "Done. Your SoftEther client and vpn-tap-ip.service were left untouched."
