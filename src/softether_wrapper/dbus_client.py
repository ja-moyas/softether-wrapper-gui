"""Asyncio D-Bus client for the privileged helper.

The client is intentionally thin: it marshals arguments, forwards the call to
the helper and wraps the raw result in :class:`CommandOutcome`.  All parsing of
``vpncmd`` output happens on this (unprivileged) side.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from dbus_next import BusType, Variant
from dbus_next.aio import MessageBus
from dbus_next.errors import DBusError

from .models import AccountSummary, CommandOutcome, Nic, SessionStatus

log = logging.getLogger("softether-wrapper-client")

BUS_NAME = "org.softether.Wrapper"
OBJ_PATH = "/org/softether/Wrapper"
IFACE = "org.softether.Wrapper.Helper"


def _bus_type() -> BusType:
    value = os.environ.get("SOFTETHER_WRAPPER_BUS", "system").strip().lower()
    return BusType.SESSION if value == "session" else BusType.SYSTEM


class HelperError(RuntimeError):
    """The helper rejected or failed to answer a call."""


class HelperUnavailable(HelperError):
    """The helper is not reachable on the system bus."""


@dataclass
class MonitorSnapshot:
    accounts: list[AccountSummary] = field(default_factory=list)
    nics: list[Nic] = field(default_factory=list)
    status: SessionStatus | None = None
    version: str = ""
    error: str = ""

    @property
    def connected_account(self) -> AccountSummary | None:
        for account in self.accounts:
            if account.is_connected:
                return account
        return None

    @property
    def is_phantom(self) -> bool:
        """A connected account whose tunnel has no transport left.

        This is the state that goes unnoticed for hours: ``AccountList`` still
        says ``Connected`` while ``AccountStatusGet`` reports ``Number of TCP
        Connections: 0`` and every byte counter at zero, so the tray stays green
        and ARP to the remote network never resolves.
        """
        status = self.status
        if status is None or self.connected_account is None:
            return False
        if status.is_connecting:
            return False
        return status.tcp_connections_count == 0


def _outcome(command: str, result: Sequence[object]) -> CommandOutcome:
    code = result[0]
    exit_code = code if isinstance(code, int) else int(str(code))
    stdout = str(result[1])
    stderr = str(result[2])
    return CommandOutcome(command=command, exit_code=exit_code, stdout=stdout, stderr=stderr)


def _marshal(args: Mapping[str, str]) -> dict[str, Variant]:
    return {str(key): Variant("s", str(value)) for key, value in args.items()}


class HelperClient:
    """A reconnecting async facade over the helper's D-Bus interface."""

    def __init__(self, connect_retries: int = 3, retry_delay: float = 1.5) -> None:
        self._bus: MessageBus | None = None
        self._iface: object | None = None
        self._lock = asyncio.Lock()
        self._connect_retries = connect_retries
        self._retry_delay = retry_delay

    @property
    def connected(self) -> bool:
        return self._iface is not None

    async def connect(self) -> None:
        if self._iface is not None:
            return
        last_error: Exception | None = None
        for attempt in range(1, self._connect_retries + 1):
            try:
                bus = await MessageBus(bus_type=_bus_type()).connect()
                node = await bus.introspect(BUS_NAME, OBJ_PATH)
                obj = bus.get_proxy_object(BUS_NAME, OBJ_PATH, node)
                self._bus = bus
                self._iface = obj.get_interface(IFACE)
                log.info("connected to %s", BUS_NAME)
                return
            except Exception as exc:  # noqa: BLE001 - retry loop
                last_error = exc
                log.warning("helper connection attempt %d failed: %s", attempt, exc)
                if attempt < self._connect_retries:
                    await asyncio.sleep(self._retry_delay)
        raise HelperUnavailable(f"helper is not available: {last_error}")

    async def close(self) -> None:
        if self._bus is not None:
            try:
                self._bus.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self._bus = None
        self._iface = None

    def _reset(self) -> None:
        self._bus = None
        self._iface = None

    async def _call(self, method: str, *args: object):
        async with self._lock:
            await self.connect()
            assert self._iface is not None
            func = getattr(self._iface, f"call_{method}")
            try:
                return await func(*args)
            except DBusError as exc:
                raise HelperError(exc.text or exc.type) from exc
            except (BrokenPipeError, EOFError, OSError) as exc:
                self._reset()
                raise HelperUnavailable(str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                self._reset()
                raise HelperUnavailable(str(exc)) from exc

    # -- simple queries ----------------------------------------------------
    async def about(self) -> str:
        return str(await self._call("about"))

    async def get_version(self) -> str:
        return str(await self._call("get_version"))

    async def client_service_status(self) -> str:
        return str(await self._call("client_service_status"))

    async def client_service_start(self) -> str:
        return str(await self._call("client_service_start"))

    async def client_service_stop(self) -> str:
        return str(await self._call("client_service_stop"))

    async def client_service_restart(self) -> str:
        return str(await self._call("client_service_restart"))

    # -- vpncmd ------------------------------------------------------------
    async def run_client(self, command: str, args: Mapping[str, str] | None = None) -> CommandOutcome:
        result = await self._call("run_client", command, _marshal(args or {}))
        return _outcome(command, result)

    async def run_tools(self, command: str, args: Mapping[str, str] | None = None) -> CommandOutcome:
        result = await self._call("run_tools", command, _marshal(args or {}))
        return _outcome(command, result)

    async def run_client_batch(
        self, commands: Sequence[tuple[str, Mapping[str, str]]]
    ) -> list[CommandOutcome]:
        payload = [[command, _marshal(args)] for command, args in commands]
        result = await self._call("run_client_batch", payload)
        return [_outcome(command, item) for (command, _), item in zip(commands, result, strict=False)]

    # -- monitoring --------------------------------------------------------
    async def monitor(self, default_account: str = "") -> MonitorSnapshot:
        from .vpncmd_parser import parse_account_list, parse_account_status, parse_nic_list

        snapshot = MonitorSnapshot()
        try:
            batch = await self.run_client_batch(
                [("VersionGet", {}), ("AccountList", {}), ("NicList", {})]
            )
        except HelperError as exc:
            snapshot.error = str(exc)
            return snapshot

        version_out, accounts_out, nics_out = batch
        snapshot.accounts = parse_account_list(accounts_out.stdout)
        snapshot.nics = parse_nic_list(nics_out.stdout)
        from .vpncmd_parser import parse_version

        snapshot.version = parse_version(version_out.stdout).version

        target = snapshot.connected_account
        name = target.name if target else default_account
        if name:
            status_outcome = await self.run_client("AccountStatusGet", {"name": name})
            if status_outcome.exit_code == 0:
                snapshot.status = parse_account_status(status_outcome.stdout)
        return snapshot
