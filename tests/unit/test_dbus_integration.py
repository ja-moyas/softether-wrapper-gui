"""End-to-end D-Bus test using a private session bus.

The helper normally talks to the system bus; these tests point both sides at an
isolated ``dbus-daemon --session`` instance via ``SOFTETHER_WRAPPER_BUS=session``
and disable polkit.
"""

import asyncio
import shutil
import subprocess

import pytest
from dbus_next import BusType
from dbus_next.aio import MessageBus

from softether_wrapper.dbus_client import BUS_NAME, OBJ_PATH, HelperClient, HelperError
from softether_wrapper_helper.service import HelperService
from softether_wrapper_helper.vpncmd_runner import CommandResult, validate_command

pytestmark = pytest.mark.skipif(
    shutil.which("dbus-daemon") is None, reason="dbus-daemon is not available"
)


class FakeRunner:
    """Validates real commands but returns canned vpncmd output."""

    def run(self, mode, commands, home=None):
        prepared = [validate_command(mode, command, args, home) for command, args in commands]
        results = []
        for item in prepared:
            results.append(
                CommandResult(
                    0,
                    f"{item.command} command - fake\nThe command completed successfully.\n",
                    "",
                )
            )
        return results


@pytest.fixture()
def session_bus(monkeypatch):
    proc = subprocess.Popen(
        ["dbus-daemon", "--session", "--print-address", "--nofork"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    line = proc.stdout.readline()
    if not line:
        proc.kill()
        pytest.skip("could not start a private dbus-daemon")
    address = line.decode().strip()
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address)
    monkeypatch.setenv("SOFTETHER_WRAPPER_BUS", "session")
    yield address
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_dbus_signatures_are_correct():
    run_client = HelperService.__dict__["RunClient"].__dict__["__DBUS_METHOD"]
    assert run_client.in_signature == "sa{sv}"
    assert run_client.out_signature == "iss"
    run_batch = HelperService.__dict__["RunClientBatch"].__dict__["__DBUS_METHOD"]
    assert run_batch.in_signature == "a(sa{sv})"
    assert run_batch.out_signature == "a(iss)"
    run_tools = HelperService.__dict__["RunTools"].__dict__["__DBUS_METHOD"]
    assert run_tools.in_signature == "sa{sv}"


def test_client_helper_roundtrip(session_bus, monkeypatch):
    def fake_systemctl(self, action):
        return subprocess.CompletedProcess(args=[action], returncode=0, stdout="active\n")

    monkeypatch.setattr(HelperService, "_systemctl", fake_systemctl)

    async def scenario():
        server_bus = await MessageBus(bus_type=BusType.SESSION).connect()
        service = HelperService(runner=FakeRunner(), polkit_enabled=False)
        server_bus.export(OBJ_PATH, service)
        server_bus.add_message_handler(service.record_message)
        await server_bus.request_name(BUS_NAME)

        client = HelperClient(connect_retries=3, retry_delay=0.1)
        try:
            outcome = await client.run_client("VersionGet", {})
            assert outcome.exit_code == 0
            assert outcome.ok

            batch = await client.run_client_batch([("AccountList", {}), ("NicList", {})])
            assert [o.exit_code for o in batch] == [0, 0]

            assert await client.client_service_status() == "active"

            mock = await client.run_tools("Check", {})
            assert mock.exit_code == 0

            service_status = await client.client_service_start()
            assert service_status == "active"
        finally:
            await client.close()
            server_bus.disconnect()

    asyncio.run(scenario())


def test_client_rejects_disallowed_command(session_bus):
    async def scenario():
        server_bus = await MessageBus(bus_type=BusType.SESSION).connect()
        service = HelperService(runner=FakeRunner(), polkit_enabled=False)
        server_bus.export(OBJ_PATH, service)
        server_bus.add_message_handler(service.record_message)
        await server_bus.request_name(BUS_NAME)

        client = HelperClient(connect_retries=3, retry_delay=0.1)
        try:
            with pytest.raises(HelperError):
                await client.run_client("ShellOut", {})
            with pytest.raises(HelperError):
                await client.run_client("AccountGet", {"name": "/etc/passwd"})
        finally:
            await client.close()
            server_bus.disconnect()

    asyncio.run(scenario())
