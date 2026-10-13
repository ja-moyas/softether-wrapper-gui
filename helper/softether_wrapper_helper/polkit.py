"""polkit integration for the helper.

The helper uses ``org.freedesktop.PolicyKit1`` to authorise every D-Bus method
call coming from the unprivileged graphical client.  The action id is defined
by the helper package (see ``packaging/polkit``).

Because dbus-next's high level service API only supports synchronous method
handlers, the (necessarily asynchronous) polkit round trip is executed on a
short-lived worker thread with its own event loop.  The service handler simply
blocks until that thread finishes; calls are serialised anyway.
"""

from __future__ import annotations

import asyncio
import pwd
import threading
from dataclasses import dataclass

POLKIT_BUS = "org.freedesktop.PolicyKit1"
POLKIT_PATH = "/org/freedesktop/PolicyKit1/Authority"
POLKIT_IFACE = "org.freedesktop.PolicyKit1.Authority"

DBUS_BUS = "org.freedesktop.DBus"
DBUS_PATH = "/org/freedesktop/DBus"
DBUS_IFACE = "org.freedesktop.DBus"

ACTION_MANAGE = "org.softether.wrapper.manage"

#: polkit flag ``AllowUserInteraction``
FLAG_ALLOW_USER_INTERACTION = 0x00000001


class AuthorizationError(RuntimeError):
    """Raised when authorization could not be obtained or determined."""


@dataclass
class CallerInfo:
    authorized: bool
    uid: int | None
    home: str | None


def _run_blocking(coro, timeout: float):
    box: dict[str, object] = {}

    def target() -> None:
        try:
            box["result"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - propagated to caller
            box["error"] = exc

    thread = threading.Thread(target=target, name="polkit", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise AuthorizationError("polkit check timed out")
    if "error" in box:
        raise AuthorizationError(str(box["error"]))
    return box.get("result")


async def _authorize_async(
    sender: str, action_id: str, allow_interaction: bool
) -> CallerInfo:
    from dbus_next import BusType, Variant
    from dbus_next.aio import MessageBus

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        dbus_node = await bus.introspect(DBUS_BUS, DBUS_PATH)
        dbus_obj = bus.get_proxy_object(DBUS_BUS, DBUS_PATH, dbus_node)
        dbus_iface = dbus_obj.get_interface(DBUS_IFACE)
        pid = await dbus_iface.call_get_connection_unix_process_id(sender)
        uid = _uid_for_pid(pid)
        home = _home_for_uid(uid)

        node = await bus.introspect(POLKIT_BUS, POLKIT_PATH)
        obj = bus.get_proxy_object(POLKIT_BUS, POLKIT_PATH, node)
        authority = obj.get_interface(POLKIT_IFACE)
        subject = ["system-bus-name", {"name": Variant("s", sender)}]
        flags = FLAG_ALLOW_USER_INTERACTION if allow_interaction else 0
        result = await authority.call_check_authorization(subject, action_id, {}, flags, "")
        authorized = bool(result[0])
        return CallerInfo(authorized=authorized, uid=uid, home=home)
    finally:
        bus.disconnect()


def authorize(
    sender: str | None,
    action_id: str = ACTION_MANAGE,
    allow_interaction: bool = True,
    timeout: float = 120.0,
) -> CallerInfo:
    """Authorise ``sender`` for ``action_id`` and resolve its home directory."""
    if not sender or not sender.startswith(":"):
        raise AuthorizationError("cannot determine the D-Bus caller identity")
    try:
        return _run_blocking(_authorize_async(sender, action_id, allow_interaction), timeout)
    except AuthorizationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AuthorizationError(f"polkit check failed: {exc}") from exc


def resolve_caller(sender: str, timeout: float = 30.0) -> CallerInfo:
    """Resolve the caller's uid/home without performing an authorization check.

    Used in test builds where polkit is disabled.
    """

    async def _resolve() -> CallerInfo:
        from dbus_next import BusType
        from dbus_next.aio import MessageBus

        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        try:
            node = await bus.introspect(DBUS_BUS, DBUS_PATH)
            obj = bus.get_proxy_object(DBUS_BUS, DBUS_PATH, node)
            iface = obj.get_interface(DBUS_IFACE)
            pid = await iface.call_get_connection_unix_process_id(sender)
            uid = _uid_for_pid(pid)
            return CallerInfo(authorized=True, uid=uid, home=_home_for_uid(uid))
        finally:
            bus.disconnect()

    return _run_blocking(_resolve(), timeout)


def _uid_for_pid(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/status", encoding="ascii", errors="replace") as stream:
            for line in stream:
                if line.startswith("Uid:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _home_for_uid(uid: int | None) -> str | None:
    if uid is None:
        return None
    try:
        return pwd.getpwuid(uid).pw_dir
    except KeyError:
        return None
