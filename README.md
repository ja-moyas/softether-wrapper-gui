# SoftEther VPN Wrapper

A graphical, system-tray front-end for the SoftEther VPN **client** on Linux.
It drives the official `vpncmd` command line utility through a small,
auditable privileged helper exposed over the system D-Bus, so the GUI never has
to run as root.

The wrapper is **additive**: it does not replace or reconfigure
`softether-vpnclient.service`, and it never touches the user-authored
`vpn-tap-ip.service` (it only *displays* the interface IP).

```
┌─────────────────────────┐        D-Bus (system bus)        ┌──────────────────────────┐
│  PySide6 tray GUI       │  org.softether.Wrapper.Helper    │  root helper (systemd)   │
│  (unprivileged user)    │ ───────────────────────────────► │  validates + runs vpncmd │
└─────────────────────────┘        polkit authorisation      └────────────┬─────────────┘
                                                                          │ argv (no shell)
                                                                          ▼
                                                              /usr/bin/vpncmd  → softether-vpnclient
```

## Components

| Path | Description |
| --- | --- |
| `src/softether_wrapper/` | PySide6 application, parser, models and D-Bus client |
| `helper/softether_wrapper_helper/` | Privileged helper: allowlist, runner, polkit, D-Bus service |
| `helper/softether_wrapper_helper/vpncmd_runner.py` | The only place that executes `vpncmd` |
| `packaging/` | systemd unit, D-Bus policy, polkit policy, desktop entry |
| `tests/` | Unit tests, D-Bus integration tests and captured `vpncmd` fixtures |
| `install.sh` / `uninstall.sh` | Install/remove the helper + GUI |

## Requirements

* A distribution-packaged SoftEther VPN client (provides `vpncmd` and
  `softether-vpnclient.service`).
* Python 3.10+.
* `PySide6` (reused system-wide when present, otherwise installed into the app
  venv) and `dbus-next` + `qasync`.
* polkit, systemd and D-Bus (standard on any desktop Linux).

## Install

```bash
sudo ./install.sh              # uses $SUDO_USER as the desktop user
sudo ./install.sh myuser       # or name the desktop user explicitly
```

The script:

1. creates `/opt/softether-wrapper/venv` (helper) with `dbus-next`;
2. copies the helper package to `/opt/softether-wrapper/lib`;
3. installs and starts `softether-wrapper-helper.service`, the D-Bus policy and
   the polkit action;
4. creates `~/.local/share/softether-wrapper/venv` for the desktop user,
   installs the GUI and desktop entry, and adds `~/.local/bin/softether-wrapper`.

The helper runs as **root**; every D-Bus method first passes a polkit check
(`org.softether.wrapper.manage`, `allow_active=yes`). The GUI itself stays
unprivileged.

To remove everything:

```bash
sudo ./uninstall.sh
```

## Usage

Launch **SoftEther VPN Wrapper** from the application menu or run
`~/.local/bin/softether-wrapper`. The tray icon reflects the state:

* grey – disconnected · amber – connecting · green – connected · red – error.
  Amber also covers *connected without transport*: the client still reports the
  account as connected but the tunnel carries no traffic (see below).

Pages:

* **Panel** – live state, counters, TAP IP, connect/disconnect, service
  start/stop/restart.
* **Cuentas** – create/edit/delete connection settings, connect/disconnect,
  export/import.
* **Adaptadores** – virtual NIC create/delete/enable/disable/MAC.
* **Certificados** – trusted CA certificates (add/delete/export) and MakeCert.
* **Herramientas** – environment check (`Check`), `About`, client version and
  certificate creation.

## Auto-recovery of hung sessions

SoftEther keeps the session object — and the "Session Established" text — after
the socket to the server dies, for instance when the machine loses its internet
connection. `AccountList` still says `Connected`, every counter in
`AccountStatusGet` sits at zero, and the TAP keeps its IP and route, so ARP to
the remote network never resolves and the connection *looks* healthy while
nothing can reach the server. Disconnecting and reconnecting by hand is the only
thing that drops the dead socket, and nothing in `vpncmd` reports the problem.

The wrapper therefore treats `Number of TCP Connections == 0` on an account the
client reports as connected as a *stale session*, shown as amber and labelled
**"Conectada sin transporte"**, and repairs it on its own:

1. after `recover_after` consecutive stale samples (default 3, i.e. ~30 s at the
   default 10 s interval) it runs `AccountDisconnect` followed by
   `AccountConnect` — in that order, with a short pause so the client can let go
   of the old session;
2. a grace window and a `recover_cooldown_s` cooldown keep it from hammering the
   client, and it never acts while a connect/disconnect you started is in
   flight;
3. after `recover_max_attempts` consecutive failures it stops and says so,
   instead of looping forever;
4. a healthy sample clears the attempt budget.

Everything is configurable in **Preferencias** (or `~/.config/softether-wrapper/softether-wrapper.conf`,
group `[monitor]`): `auto_recover`, `recover_after`, `recover_cooldown_s`,
`recover_max_attempts`. The wrapper only issues `AccountConnect` /
`AccountDisconnect`; it still never touches the TAP address owned by
`vpn-tap-ip.service`.

## Security model

* The helper accepts **only** commands from a fixed allowlist, per mode
  (`client` / `tools`). Every argument is validated (type, length, charset and
  enum); file paths must resolve inside the caller's home directory.
* `vpncmd` is always executed with an explicit `argv` list. **No shell is ever
  used**, so argument values cannot be re-interpreted as commands.
* Commands carrying secrets (passwords, private keys) are sent through a
  `0600` `/IN` file inside the helper `RuntimeDirectory`, never on the command
  line (`/proc/<pid>/cmdline`).
* `stdin` is `/dev/null` and every invocation has a timeout, so a missing
  argument can never hang the helper on an interactive prompt.
* Calls are serialised with a global lock (SoftEther's local IPC tolerates a
  single management connection).

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]' dbus-next qasync
.venv/bin/python -m pytest        # unit + D-Bus integration tests
ruff check src helper tests
mypy
```

The GUI can be smoke-tested head-less:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m softether_wrapper
```

### Fixtures

`tests/fixtures/*.txt` are real `vpncmd` v5.01 outputs (sanitised). Parsers are
pinned to them. To refresh against a live client:

```bash
python tests/capture_fixtures.py        # writes tests/fixtures/*.txt
```

### Manual end-to-end checklist

These steps need a real session/polkit and cannot be automated in CI:

1. `systemctl status softether-wrapper-helper.service` → active.
2. Launch the GUI; the tray icon turns green if an account is connected.
3. Connect/disconnect an account; confirm the tray tooltip and counters.
4. Edit a connection, set a password, reconnect.
5. `journalctl -u softether-wrapper-helper.service` shows no errors.
6. Confirm `vpn-tap-ip.service` still owns `vpn_vpn0` and the IP is only
   displayed, never modified.
7. Auto-recovery: with a healthy session, block the way out to the server
   (`sudo iptables -I OUTPUT -d <server-ip> -p tcp --dport 443 -j DROP`), watch
   the tray turn amber, then remove the rule
   (`sudo iptables -D OUTPUT -d <server-ip> -p tcp --dport 443 -j DROP`) and
   confirm the wrapper reconnects on its own (`Number of TCP Connections` back
   at 2) without any manual action.

## Notes / limitations

* `AccountSecureCertSet` and smart-card flows are best-effort; they depend on
  hardware not present on most systems.
* Traffic test tools (`TrafficClient`/`TrafficServer`) are intentionally not
  exposed in v1.
* The helper needs access to user home directories to import/export settings
  and certificates; the systemd unit therefore relaxes `ProtectHome`.
