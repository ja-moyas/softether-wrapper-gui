#!/usr/bin/env python3
"""Regenerate the ``tests/fixtures`` files from a live ``vpncmd``.

The committed fixtures are **sanitised** real outputs.  This helper captures raw
output so you can diff it against a running client; review and redact sensitive
values (host names, usernames, session keys) before committing.

Usage:
    python tests/capture_fixtures.py [--account NAME] [--out DIR]
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
VPNCMD = os.environ.get("SOFTETHER_WRAPPER_VPNCMD", "vpncmd")
TIMEOUT = 60


def run(argv: list[str]) -> str:
    env = dict(os.environ)
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"
    completed = subprocess.run(
        [VPNCMD, *argv],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        timeout=TIMEOUT,
        check=False,
    )
    return completed.stdout.decode("utf-8", "replace")


def client(command: str, *extra: str) -> str:
    return run(["localhost", "/CLIENT", "/CMD", command, *extra])


def tools(command: str, *extra: str) -> str:
    return run(["/TOOLS", "/CMD", command, *extra])


def first_account() -> str:
    match = re.search(r"VPN Connection Setting Name \|(.+)", client("AccountList"))
    return match.group(1).strip() if match else "MyVPN"


def write(out_dir: Path, name: str, text: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text(text, encoding="utf-8")
    print(f"wrote {name} ({len(text)} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", help="account name for AccountGet/StatusGet")
    parser.add_argument("--out", default=str(FIXTURE_DIR))
    args = parser.parse_args()

    out_dir = Path(args.out)
    account = args.account or first_account()
    print(f"capturing for account: {account}")

    write(out_dir, "about.txt", tools("About"))
    write(out_dir, "versionget.txt", client("VersionGet"))
    write(out_dir, "passwordget.txt", client("PasswordGet"))
    write(out_dir, "niclist.txt", client("NicList"))
    write(out_dir, "certlist_empty.txt", client("CertList"))
    write(out_dir, "securelist_empty.txt", client("SecureList"))
    write(out_dir, "accountlist_multi.txt", client("AccountList"))
    write(out_dir, "accountget.txt", client("AccountGet", account))
    write(out_dir, "accountstatus_connected.txt", client("AccountStatusGet", account))
    write(out_dir, "keepget.txt", client("KeepGet"))
    write(out_dir, "check_fail.txt", tools("Check"))
    write(out_dir, "makecert_help.txt", tools("MakeCert", "/?"))
    write(out_dir, "error_account_missing.txt", client("AccountGet", "NoSuchAccountZZZ"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
