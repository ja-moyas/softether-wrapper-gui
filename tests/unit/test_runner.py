import json
import shutil
import stat
from pathlib import Path

import pytest

from softether_wrapper_helper.vpncmd_runner import (
    ValidationError,
    VpncmdRunner,
    split_command_blocks,
    validate_command,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FAKE_SOURCE = Path(__file__).resolve().parents[1] / "fakes" / "fake_vpncmd.py"


@pytest.fixture()
def fake_vpncmd(tmp_path, monkeypatch):
    target = tmp_path / "vpncmd"
    shutil.copy(FAKE_SOURCE, target)
    target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    record = tmp_path / "record.jsonl"
    monkeypatch.setenv("FAKE_VPNCMD_RECORD", str(record))
    return target, record, tmp_path


def read_records(record: Path):
    if not record.exists():
        return []
    return [json.loads(line) for line in record.read_text().splitlines() if line.strip()]


# --- validation ------------------------------------------------------------
def test_render_basic_command():
    prepared = validate_command("client", "AccountGet", {"name": "MyVPN"}, home="/home/alice")
    assert prepared.render() == "AccountGet MyVPN"
    assert not prepared.sensitive


def test_render_quotes_values_with_spaces():
    prepared = validate_command(
        "client", "AccountSet", {"name": "My VPN", "HUB": "My Hub"}, home="/home/alice"
    )
    assert prepared.render() == 'AccountSet "My VPN" /HUB:"My Hub"'


def test_rejects_unknown_command():
    with pytest.raises(ValidationError):
        validate_command("client", "ShellOut", {}, None)


def test_rejects_extra_argument():
    with pytest.raises(ValidationError):
        validate_command("client", "AccountDelete", {"name": "x", "FORCE": "yes"}, None)


def test_rejects_missing_required_positional():
    with pytest.raises(ValidationError):
        validate_command("client", "AccountGet", {}, None)


def test_rejects_leading_slash_name():
    with pytest.raises(ValidationError):
        validate_command("client", "AccountGet", {"name": "/etc/passwd"}, None)


def test_rejects_command_injection_in_host():
    with pytest.raises(ValidationError):
        validate_command("client", "AccountCreate", {"name": "a", "SERVER": "host;rm -rf /"}, None)


def test_rejects_control_characters():
    with pytest.raises(ValidationError):
        validate_command("client", "AccountGet", {"name": "a\nb"}, None)


def test_rejects_invalid_mac():
    with pytest.raises(ValidationError):
        validate_command("client", "NicSetSetting", {"name": "vpn0", "MAC": "nope"}, None)


def test_rejects_path_outside_home(tmp_path):
    other = tmp_path / "home" / "alice"
    other.mkdir(parents=True)
    with pytest.raises(ValidationError):
        validate_command("client", "AccountImport", {"path": "/etc/shadow"}, home=str(other))


def test_allows_path_inside_home(tmp_path):
    home = tmp_path / "home" / "alice"
    home.mkdir(parents=True)
    prepared = validate_command(
        "client", "AccountImport", {"path": str(home / "a.vpn")}, home=str(home)
    )
    assert prepared.render().endswith("a.vpn")


# --- construction ----------------------------------------------------------
def test_vpncmd_path_from_env(monkeypatch):
    monkeypatch.setenv("SOFTETHER_WRAPPER_VPNCMD", "/opt/softether/vpncmd")
    assert VpncmdRunner().vpncmd_path == "/opt/softether/vpncmd"


def test_vpncmd_path_explicit_wins(monkeypatch):
    monkeypatch.setenv("SOFTETHER_WRAPPER_VPNCMD", "/opt/softether/vpncmd")
    assert VpncmdRunner(vpncmd_path="/usr/bin/vpncmd").vpncmd_path == "/usr/bin/vpncmd"


# --- execution with a fake vpncmd -----------------------------------------
def test_non_sensitive_uses_cmd_capability(fake_vpncmd):
    binary, record, _ = fake_vpncmd
    runner = VpncmdRunner(vpncmd_path=str(binary))
    results = runner.run("client", [("AccountList", {})])
    assert results[0].exit_code == 0
    argv = read_records(record)[0]["argv"]
    assert "/CMD" in argv
    assert not any(token.startswith("/IN:") for token in argv)


def test_sensitive_value_hidden_from_argv(fake_vpncmd):
    binary, record, _ = fake_vpncmd
    runner = VpncmdRunner(vpncmd_path=str(binary))
    runner.run("client", [("AccountPasswordSet", {"name": "MyVPN", "PASSWORD": "s3cr3t!"})])
    records = read_records(record)
    argv = records[0]["argv"]
    assert any(token.startswith("/IN:") for token in argv)
    assert all("s3cr3t!" not in token for token in argv)
    assert records[0]["in_content"] is not None
    assert "s3cr3t!" in records[0]["in_content"]


def test_batch_maps_per_command_exit_codes(fake_vpncmd):
    binary, record, _ = fake_vpncmd
    runner = VpncmdRunner(vpncmd_path=str(binary))
    results = runner.run(
        "client",
        [("VersionGet", {}), ("AccountGet", {"name": "MissingVPN"}), ("NicList", {})],
    )
    assert [r.exit_code for r in results] == [0, 36, 0]
    assert results[1].error_code == 36


def test_split_command_blocks_from_real_batch():
    text = (FIXTURES / "batch_combined.txt").read_text(encoding="utf-8")
    blocks = split_command_blocks(text)
    assert [cmd.split()[0] for cmd, _ in blocks] == [
        "VersionGet",
        "AccountList",
        "AccountGet",
        "NicList",
    ]
    assert "Error occurred. (Error code: 36)" in blocks[2][1]


def test_tools_makecert_uses_in_file(fake_vpncmd):
    binary, record, tmp_path = fake_vpncmd
    home = tmp_path / "home"
    home.mkdir()
    runner = VpncmdRunner(vpncmd_path=str(binary))
    runner.run(
        "tools",
        [("MakeCert", {"CN": "Test", "SAVECERT": str(home / "c.cer")})],
        home=str(home),
    )
    argv = read_records(record)[0]["argv"]
    assert argv == ["/TOOLS", "/CMD", "MakeCert", "/CN:Test", f"/SAVECERT:{home / 'c.cer'}"]
