# ruff: noqa: UP037, F821, F722
"""D-Bus service exposing the validated SoftEther ``vpncmd`` wrapper helper.

Bus name:   ``org.softether.Wrapper``
Object path ``/org/softether/Wrapper``
Interface:  ``org.softether.Wrapper.Helper``
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from collections.abc import Mapping

from dbus_next import BusType, DBusError, Message, MessageType, Variant
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method

from . import polkit
from .vpncmd_runner import ValidationError, VpncmdRunner

BUS_NAME = "org.softether.Wrapper"
OBJ_PATH = "/org/softether/Wrapper"
IFACE_NAME = "org.softether.Wrapper.Helper"

VPNCLIENT_SERVICE = "softether-vpnclient.service"

ERR_GENERAL = "org.softether.Wrapper.Error"
ERR_NOT_AUTHORIZED = "org.softether.Wrapper.NotAuthorized"
ERR_INVALID_ARGS = "org.softether.Wrapper.InvalidArgs"

log = logging.getLogger("softether-wrapper-helper")


def _bus_type() -> BusType:
    value = os.environ.get("SOFTETHER_WRAPPER_BUS", "system").strip().lower()
    return BusType.SESSION if value == "session" else BusType.SYSTEM


def _unwrap_args(args: Mapping[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in args.items():
        if isinstance(value, Variant):
            value = value.value
        if not isinstance(value, str):
            raise ValidationError(f"argument {key!r} must be a string")
        result[str(key)] = value
    return result


class HelperService(ServiceInterface):
    def __init__(
        self,
        runner: VpncmdRunner | None = None,
        polkit_enabled: bool | None = None,
        action_id: str = polkit.ACTION_MANAGE,
    ) -> None:
        super().__init__(IFACE_NAME)
        self.runner = runner or VpncmdRunner()
        if polkit_enabled is None:
            polkit_enabled = os.environ.get("SOFTETHER_WRAPPER_NO_POLKIT") != "1"
        self.polkit_enabled = polkit_enabled
        self.action_id = action_id
        self._current_sender: str | None = None

    # -- caller tracking ---------------------------------------------------
    def record_message(self, msg: Message) -> bool:
        if (
            msg.message_type == MessageType.METHOD_CALL
            and msg.interface == IFACE_NAME
            and msg.path == OBJ_PATH
        ):
            self._current_sender = msg.sender
        return False

    def _authorize(self) -> polkit.CallerInfo:
        if not self.polkit_enabled:
            return polkit.CallerInfo(True, None, None)
        try:
            info = polkit.authorize(self._current_sender, self.action_id)
        except polkit.AuthorizationError as exc:
            raise DBusError(ERR_NOT_AUTHORIZED, str(exc)) from exc
        if not info.authorized:
            raise DBusError(ERR_NOT_AUTHORIZED, "authorization was denied")
        return info

    def _run(
        self, mode: str, command: str, args: Mapping[str, object], home: str | None
    ) -> list[object]:
        try:
            results = self.runner.run(mode, [(command, args)], home=home)
        except ValidationError as exc:
            raise DBusError(ERR_INVALID_ARGS, str(exc)) from exc
        return list(results[0].as_tuple())

    def _run_many(
        self, mode: str, commands: list[tuple[str, Mapping[str, object]]], home: str | None
    ) -> list[list[object]]:
        try:
            results = self.runner.run(mode, commands, home=home)
        except ValidationError as exc:
            raise DBusError(ERR_INVALID_ARGS, str(exc)) from exc
        return [list(result.as_tuple()) for result in results]

    # -- systemd -----------------------------------------------------------
    @staticmethod
    def _systemctl(action: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["systemctl", action, VPNCLIENT_SERVICE],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
            text=True,
        )

    @method()
    def ClientServiceStatus(self) -> "s":
        self._authorize()
        completed = self._systemctl("is-active")
        state = (completed.stdout or "").strip()
        if state not in {"active", "inactive", "failed", "activating", "deactivating"}:
            state = "failed" if completed.returncode else "inactive"
        return state

    def _service_action(self, action: str) -> str:
        self._authorize()
        completed = self._systemctl(action)
        output = (completed.stdout or "").strip()
        if completed.returncode != 0:
            raise DBusError(ERR_GENERAL, output or f"systemctl {action} failed")
        return output or "ok"

    @method()
    def ClientServiceStart(self) -> "s":
        return self._service_action("start")

    @method()
    def ClientServiceStop(self) -> "s":
        return self._service_action("stop")

    @method()
    def ClientServiceRestart(self) -> "s":
        return self._service_action("restart")

    # -- vpncmd ------------------------------------------------------------
    def _run_text(self, mode: str, command: str) -> str:
        code, stdout, stderr = self._run(mode, command, {}, None)
        text = str(stdout)
        if str(code) != "0":
            text += str(stderr)
        return text

    @method()
    def About(self) -> "s":
        self._authorize()
        return self._run_text("tools", "About")

    @method()
    def GetVersion(self) -> "s":
        self._authorize()
        return self._run_text("client", "VersionGet")

    @method()
    def RunClient(self, command: "s", args: "a{sv}") -> "iss":
        info = self._authorize()
        return self._run("client", command, _unwrap_args(args), info.home)

    @method()
    def RunClientBatch(self, commands: "a(sa{sv})") -> "a(iss)":
        info = self._authorize()
        normalised: list[tuple[str, Mapping[str, object]]] = []
        for command, args in commands:
            normalised.append((command, _unwrap_args(args)))
        return self._run_many("client", normalised, info.home)

    @method()
    def RunTools(self, command: "s", args: "a{sv}") -> "iss":
        info = self._authorize()
        return self._run("tools", command, _unwrap_args(args), info.home)


async def _serve() -> None:
    bus_type = _bus_type()
    bus = await MessageBus(bus_type=bus_type).connect()
    service = HelperService()
    bus.export(OBJ_PATH, service)
    bus.add_message_handler(service.record_message)
    await bus.request_name(BUS_NAME)
    log.info("helper is listening on %s", BUS_NAME)
    await bus.wait_for_disconnect()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
