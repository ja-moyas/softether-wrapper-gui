"""QIcon accessors for the connection-state icons."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from PySide6.QtGui import QIcon

from ..models import ConnectionState

ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"

_STATE_FILES = {
    ConnectionState.CONNECTED: "state-connected.svg",
    ConnectionState.CONNECTING: "state-connecting.svg",
    ConnectionState.DISCONNECTED: "state-disconnected.svg",
    # Reported connected but carrying no transport: amber, like a connection in
    # progress, because that is exactly what the wrapper is doing about it.
    ConnectionState.STALE: "state-connecting.svg",
    ConnectionState.UNKNOWN: "state-disconnected.svg",
    "error": "state-error.svg",
}


@cache
def state_icon(state: ConnectionState | str) -> QIcon:
    filename = _STATE_FILES.get(state, "state-disconnected.svg")
    path = ICON_DIR / filename
    if path.exists():
        return QIcon(str(path))
    return QIcon()
