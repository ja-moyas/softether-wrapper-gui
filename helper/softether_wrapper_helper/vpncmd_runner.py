"""Thin, auditable executor for the SoftEther ``vpncmd`` command line utility.

Security model
--------------
* The helper accepts only commands present in the per-mode allowlist defined
  below.  Every argument is validated by a dedicated validator (type, length,
  character set, and - for file paths - confinement to the caller's home
  directory).
* ``vpncmd`` is always invoked through an explicit ``argv`` list.  A shell is
  never used, so argument values can never be re-interpreted as commands.
* Commands that carry secret values (passwords, private keys) are routed
  through a ``0600`` ``/IN`` file inside the helper ``RuntimeDirectory`` so
  that the secrets never appear in ``/proc/<pid>/cmdline``.
* Calls are serialised with a global lock: the SoftEther local IPC endpoint
  only tolerates one management connection at a time.
* ``stdin`` is redirected to ``/dev/null`` so a missing argument can never make
  ``vpncmd`` block forever on an interactive prompt.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

SUCCESS_MARKERS = (
    "The command completed successfully.",
    "The command terminated normally.",
)
ERROR_RE = re.compile(r"Error occurred\. \(Error code: (\d+)\)")
PROMPT_RE = re.compile(r"^(?:VPN Client|VPN Tools)>(.*)$", re.MULTILINE)

#: Options whose value must never reach the process command line.
SENSITIVE_OPTIONS = frozenset({"PASSWORD", "LOADKEY", "SIGNKEY"})

DEFAULT_CLIENT_TIMEOUT = 15.0
DEFAULT_TOOLS_TIMEOUT = 60.0

_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_HOST_RE = re.compile(r"^[A-Za-z0-9._\-]{1,253}$")
_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$")

Validator = Callable[[str, str | None], str]


class ValidationError(ValueError):
    """Raised when a command name or one of its arguments is not allowed."""


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
def _base(value: object, *, max_len: int) -> str:
    if not isinstance(value, str):
        raise ValidationError("argument value must be a string")
    if not value:
        raise ValidationError("argument value must not be empty")
    if len(value) > max_len:
        raise ValidationError("argument value is too long")
    if _CTRL_RE.search(value):
        raise ValidationError("control characters are not allowed")
    if '"' in value:
        raise ValidationError("double quotes are not allowed")
    return value


def v_name(value: str, home: str | None) -> str:
    """A connection/NIC name: free text, no leading slash, max 64 chars."""
    value = _base(value, max_len=64)
    if value.startswith("/"):
        raise ValidationError("names must not start with '/'")
    return value


def v_text(value: str, home: str | None) -> str:
    """Free text (hub name, user name, certificate object name)."""
    value = _base(value, max_len=255)
    if value.startswith("/"):
        raise ValidationError("values must not start with '/'")
    return value


def v_password(value: str, home: str | None) -> str:
    return _base(value, max_len=255)


def v_hostport(value: str, home: str | None) -> str:
    value = _base(value, max_len=260)
    host, sep, port = value.rpartition(":")
    if sep and _HOST_RE.match(host):
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            raise ValidationError("port must be between 1 and 65535")
        return value
    if _HOST_RE.match(value):
        return value
    raise ValidationError("expected 'host' or 'host:port'")


def v_mac(value: str, home: str | None) -> str:
    value = _base(value, max_len=17)
    if not _MAC_RE.match(value):
        raise ValidationError("invalid MAC address")
    return value


def v_integer(low: int, high: int) -> Validator:
    def _validator(value: str, home: str | None) -> str:
        value = _base(value, max_len=10)
        if not value.isdigit():
            raise ValidationError("expected a non-negative integer")
        number = int(value)
        if not (low <= number <= high):
            raise ValidationError(f"integer must be between {low} and {high}")
        return str(number)

    return _validator


def v_enum(*allowed: str) -> Validator:
    allowed_set = {a.lower() for a in allowed}

    def _validator(value: str, home: str | None) -> str:
        value = _base(value, max_len=32)
        lowered = value.lower()
        if lowered not in allowed_set:
            raise ValidationError(f"expected one of: {', '.join(sorted(allowed_set))}")
        return lowered

    return _validator


def v_path(write: bool = False) -> Validator:
    """An absolute path confined to the caller's home directory.

    Symlinks are resolved with :func:`os.path.realpath` so a path can never
    escape the home directory by traversal or by a symlink.
    """

    def _validator(value: str, home: str | None) -> str:
        value = _base(value, max_len=4096)
        if not value.startswith("/"):
            raise ValidationError("path must be absolute")
        if not home:
            raise ValidationError("caller home directory could not be determined")
        real = os.path.realpath(value)
        root = os.path.realpath(home)
        if real != root and not real.startswith(root + os.sep):
            raise ValidationError("path must stay inside your home directory")
        return value

    return _validator


V_YESNO = v_enum("yes", "no")


# ---------------------------------------------------------------------------
# Command specs and allowlist
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CommandSpec:
    name: str
    positional: tuple[tuple[str, Validator, bool], ...] = ()
    options: Mapping[str, Validator] = field(default_factory=dict)
    #: True when a positional argument itself is sensitive (e.g. PasswordSet).
    sensitive_positional: bool = False


def _pos(name: str, validator: Validator, required: bool = True) -> tuple[str, Validator, bool]:
    return (name, validator, required)


def _spec(
    name: str,
    positional: Sequence[tuple[str, Validator, bool]] = (),
    options: Mapping[str, Validator] | None = None,
    sensitive_positional: bool = False,
) -> CommandSpec:
    return CommandSpec(
        name=name,
        positional=tuple(positional),
        options=dict(options or {}),
        sensitive_positional=sensitive_positional,
    )


_ACCOUNT_DETAIL_OPTIONS: dict[str, Validator] = {
    "MAXTCP": v_integer(1, 32),
    "INTERVAL": v_integer(0, 3600),
    "TTL": v_integer(0, 86400),
    "HALF": V_YESNO,
    "BRIDGE": V_YESNO,
    "MONITOR": V_YESNO,
    "NOTRACK": V_YESNO,
    "NOQOS": V_YESNO,
}

_MAKECERT_OPTIONS: dict[str, Validator] = {
    "CN": v_text,
    "O": v_text,
    "OU": v_text,
    "C": v_text,
    "ST": v_text,
    "L": v_text,
    "SERIAL": v_text,
    "EXPIRES": v_text,
    "SIGNCERT": v_path(),
    "SIGNKEY": v_path(),
    "SAVECERT": v_path(write=True),
    "SAVEKEY": v_path(write=True),
}

CLIENT_COMMANDS: dict[str, CommandSpec] = {
    "About": _spec("About"),
    "VersionGet": _spec("VersionGet"),
    "PasswordGet": _spec("PasswordGet"),
    "PasswordSet": _spec(
        "PasswordSet",
        positional=[_pos("password", v_password)],
        options={"REMOTEONLY": V_YESNO},
        sensitive_positional=True,
    ),
    # Certificates (trusted CA list)
    "CertList": _spec("CertList"),
    "CertAdd": _spec("CertAdd", positional=[_pos("path", v_path())]),
    "CertDelete": _spec("CertDelete", positional=[_pos("id", v_integer(0, 2**31 - 1))]),
    "CertGet": _spec(
        "CertGet",
        positional=[_pos("id", v_integer(0, 2**31 - 1))],
        options={"SAVECERT": v_path(write=True)},
    ),
    # Smart cards
    "SecureList": _spec("SecureList"),
    "SecureSelect": _spec("SecureSelect", positional=[_pos("id", v_integer(0, 2**31 - 1))]),
    "SecureGet": _spec("SecureGet"),
    # Virtual NICs
    "NicCreate": _spec("NicCreate", positional=[_pos("name", v_name)]),
    "NicDelete": _spec("NicDelete", positional=[_pos("name", v_name)]),
    "NicUpgrade": _spec("NicUpgrade", positional=[_pos("name", v_name)]),
    "NicGetSetting": _spec("NicGetSetting", positional=[_pos("name", v_name)]),
    "NicSetSetting": _spec("NicSetSetting", positional=[_pos("name", v_name)], options={"MAC": v_mac}),
    "NicEnable": _spec("NicEnable", positional=[_pos("name", v_name)]),
    "NicDisable": _spec("NicDisable", positional=[_pos("name", v_name)]),
    "NicList": _spec("NicList"),
    # Accounts
    "AccountList": _spec("AccountList"),
    "AccountCreate": _spec(
        "AccountCreate",
        positional=[_pos("name", v_name)],
        options={
            "SERVER": v_hostport,
            "HUB": v_text,
            "USERNAME": v_text,
            "NICNAME": v_name,
        },
    ),
    "AccountSet": _spec(
        "AccountSet",
        positional=[_pos("name", v_name)],
        options={"SERVER": v_hostport, "HUB": v_text},
    ),
    "AccountGet": _spec("AccountGet", positional=[_pos("name", v_name)]),
    "AccountDelete": _spec("AccountDelete", positional=[_pos("name", v_name)]),
    "AccountRename": _spec(
        "AccountRename", positional=[_pos("name", v_name)], options={"NEW": v_name}
    ),
    "AccountUsernameSet": _spec(
        "AccountUsernameSet", positional=[_pos("name", v_name)], options={"USERNAME": v_text}
    ),
    "AccountAnonymousSet": _spec("AccountAnonymousSet", positional=[_pos("name", v_name)]),
    "AccountPasswordSet": _spec(
        "AccountPasswordSet",
        positional=[_pos("name", v_name)],
        options={"PASSWORD": v_password, "TYPE": v_enum("standard", "radius")},
    ),
    "AccountCertSet": _spec(
        "AccountCertSet",
        positional=[_pos("name", v_name)],
        options={"LOADCERT": v_path(), "LOADKEY": v_path()},
    ),
    "AccountCertGet": _spec(
        "AccountCertGet",
        positional=[_pos("name", v_name)],
        options={"SAVECERT": v_path(write=True)},
    ),
    "AccountEncryptEnable": _spec("AccountEncryptEnable", positional=[_pos("name", v_name)]),
    "AccountEncryptDisable": _spec("AccountEncryptDisable", positional=[_pos("name", v_name)]),
    "AccountCompressEnable": _spec("AccountCompressEnable", positional=[_pos("name", v_name)]),
    "AccountCompressDisable": _spec("AccountCompressDisable", positional=[_pos("name", v_name)]),
    "AccountProxyNone": _spec("AccountProxyNone", positional=[_pos("name", v_name)]),
    "AccountProxyHttp": _spec(
        "AccountProxyHttp",
        positional=[_pos("name", v_name)],
        options={"SERVER": v_hostport, "USERNAME": v_text, "PASSWORD": v_password},
    ),
    "AccountProxySocks": _spec(
        "AccountProxySocks",
        positional=[_pos("name", v_name)],
        options={"SERVER": v_hostport, "USERNAME": v_text, "PASSWORD": v_password},
    ),
    "AccountServerCertEnable": _spec(
        "AccountServerCertEnable", positional=[_pos("name", v_name)]
    ),
    "AccountServerCertDisable": _spec(
        "AccountServerCertDisable", positional=[_pos("name", v_name)]
    ),
    "AccountServerCertSet": _spec(
        "AccountServerCertSet",
        positional=[_pos("name", v_name)],
        options={"LOADCERT": v_path()},
    ),
    "AccountServerCertDelete": _spec(
        "AccountServerCertDelete", positional=[_pos("name", v_name)]
    ),
    "AccountServerCertGet": _spec(
        "AccountServerCertGet",
        positional=[_pos("name", v_name)],
        options={"SAVECERT": v_path(write=True)},
    ),
    "AccountDetailSet": _spec(
        "AccountDetailSet", positional=[_pos("name", v_name)], options=_ACCOUNT_DETAIL_OPTIONS
    ),
    "AccountNicSet": _spec(
        "AccountNicSet", positional=[_pos("name", v_name)], options={"NICNAME": v_name}
    ),
    "AccountRetrySet": _spec(
        "AccountRetrySet",
        positional=[_pos("name", v_name)],
        options={"NUM": v_integer(0, 999), "INTERVAL": v_integer(0, 86400)},
    ),
    "AccountStartupSet": _spec("AccountStartupSet", positional=[_pos("name", v_name)]),
    "AccountStartupRemove": _spec("AccountStartupRemove", positional=[_pos("name", v_name)]),
    "AccountConnect": _spec("AccountConnect", positional=[_pos("name", v_name)]),
    "AccountDisconnect": _spec("AccountDisconnect", positional=[_pos("name", v_name)]),
    "AccountStatusGet": _spec("AccountStatusGet", positional=[_pos("name", v_name)]),
    "AccountStatusShow": _spec("AccountStatusShow", positional=[_pos("name", v_name)]),
    "AccountStatusHide": _spec("AccountStatusHide", positional=[_pos("name", v_name)]),
    "AccountSecureCertSet": _spec(
        "AccountSecureCertSet",
        positional=[_pos("name", v_name)],
        options={"CERTNAME": v_text, "KEYNAME": v_text},
    ),
    "AccountExport": _spec(
        "AccountExport",
        positional=[_pos("name", v_name)],
        options={"SAVEPATH": v_path(write=True)},
    ),
    "AccountImport": _spec("AccountImport", positional=[_pos("path", v_path())]),
    "RemoteEnable": _spec("RemoteEnable"),
    "RemoteDisable": _spec("RemoteDisable"),
    "KeepEnable": _spec("KeepEnable"),
    "KeepDisable": _spec("KeepDisable"),
    "KeepSet": _spec(
        "KeepSet",
        options={
            "HOST": v_hostport,
            "PROTOCOL": v_enum("tcp", "udp"),
            "INTERVAL": v_integer(1, 86400),
        },
    ),
    "KeepGet": _spec("KeepGet"),
}

TOOLS_COMMANDS: dict[str, CommandSpec] = {
    "About": _spec("About"),
    "Check": _spec("Check"),
    "MakeCert": _spec("MakeCert", options=_MAKECERT_OPTIONS),
    "HELP": _spec("HELP", positional=[_pos("command", v_text, required=False)]),
}

ALLOWLIST: Mapping[str, Mapping[str, CommandSpec]] = {
    "client": CLIENT_COMMANDS,
    "tools": TOOLS_COMMANDS,
}


# ---------------------------------------------------------------------------
# Validation + command-line building
# ---------------------------------------------------------------------------
@dataclass
class PreparedCommand:
    command: str
    tokens: list[str]
    spec: CommandSpec

    @property
    def sensitive(self) -> bool:
        if self.spec.sensitive_positional and self.spec.positional:
            return True
        for token in self.tokens:
            if token.startswith("/") and ":" in token:
                key = token[1:].split(":", 1)[0]
                if key in SENSITIVE_OPTIONS:
                    return True
        return False

    def render(self) -> str:
        parts = [self.command]
        for token in self.tokens:
            if token.startswith("/") and ":" in token:
                key, _, value = token.partition(":")
                if " " in value:
                    parts.append(f'{key}:"{value}"')
                else:
                    parts.append(token)
            elif " " in token:
                parts.append(f'"{token}"')
            else:
                parts.append(token)
        return " ".join(parts)


def validate_command(
    mode: str,
    command: str,
    args: Mapping[str, object],
    home: str | None = None,
) -> PreparedCommand:
    table = ALLOWLIST.get(mode)
    if table is None:
        raise ValidationError(f"unknown mode: {mode}")
    if not isinstance(command, str):
        raise ValidationError("command must be a string")
    spec = table.get(command)
    if spec is None:
        raise ValidationError(f"command not allowed: {command}")
    if args is None:
        args = {}
    if not isinstance(args, Mapping):
        raise ValidationError("args must be a mapping")
    provided = {str(k): v for k, v in args.items()}

    allowed_keys = {name for name, _, _ in spec.positional} | set(spec.options)
    for key in provided:
        if key not in allowed_keys:
            raise ValidationError(f"argument not allowed for {command}: {key}")

    tokens: list[str] = []
    for name, validator, required in spec.positional:
        if name not in provided or provided[name] in (None, ""):
            if required:
                raise ValidationError(f"missing required argument: {name}")
            continue
        tokens.append(validator(provided[name], home))  # type: ignore[arg-type]

    for key, validator in spec.options.items():
        if key not in provided or provided[key] in (None, ""):
            continue
        tokens.append(f"/{key}:{validator(provided[key], home)}")  # type: ignore[arg-type]

    return PreparedCommand(command=command, tokens=tokens, spec=spec)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and any(m in self.stdout for m in SUCCESS_MARKERS)

    @property
    def error_code(self) -> int | None:
        match = ERROR_RE.search(self.stdout)
        return int(match.group(1)) if match else None

    def as_tuple(self) -> tuple[int, str, str]:
        return (self.exit_code, self.stdout, self.stderr)


def split_command_blocks(text: str) -> list[tuple[str, str]]:
    """Split combined ``/IN`` output into ``(command_line, block)`` pairs."""
    matches = list(PROMPT_RE.finditer(text))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((match.group(1).strip(), text[start:end]))
    return blocks


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
class VpncmdRunner:
    """Serialises and executes ``vpncmd`` invocations."""

    def __init__(
        self,
        vpncmd_path: str | None = None,
        timeout: float = DEFAULT_CLIENT_TIMEOUT,
        tools_timeout: float = DEFAULT_TOOLS_TIMEOUT,
        runtime_dir: str | None = None,
    ) -> None:
        self.vpncmd_path = (
            vpncmd_path
            or os.environ.get("SOFTETHER_WRAPPER_VPNCMD")
            or shutil.which("vpncmd")
            or "/usr/bin/vpncmd"
        )
        self.timeout = timeout
        self.tools_timeout = tools_timeout
        self.runtime_dir = runtime_dir or os.environ.get("RUNTIME_DIRECTORY") or None
        self._lock = threading.Lock()

    # -- environment -------------------------------------------------------
    def _environment(self) -> dict[str, str]:
        env = dict(os.environ)
        env["LANG"] = "C.UTF-8"
        env["LC_ALL"] = "C.UTF-8"
        return env

    def _temp_dir(self) -> str:
        candidates = []
        if self.runtime_dir:
            candidates.append(self.runtime_dir)
        candidates.append(tempfile.gettempdir())
        for candidate in candidates:
            if os.path.isdir(candidate) and os.access(candidate, os.W_OK):
                return candidate
        return tempfile.mkdtemp(prefix="softether-wrapper-")

    def _base_argv(self, mode: str) -> list[str]:
        if mode == "client":
            return [self.vpncmd_path, "localhost", "/CLIENT"]
        if mode == "tools":
            return [self.vpncmd_path, "/TOOLS"]
        raise ValidationError(f"unknown mode: {mode}")

    def _timeout_for(self, mode: str) -> float:
        return self.tools_timeout if mode == "tools" else self.timeout

    def _call(self, argv: list[str], mode: str) -> CommandResult:
        try:
            completed = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                env=self._environment(),
                timeout=self._timeout_for(mode),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _decode(exc.stdout)
            stderr = _decode(exc.stderr)
            message = f"vpncmd timed out after {self._timeout_for(mode):.0f}s\n"
            return CommandResult(-1, stdout, stderr + message)
        except OSError as exc:
            return CommandResult(-1, "", f"failed to execute vpncmd: {exc}\n")
        return CommandResult(completed.returncode, _decode(completed.stdout), _decode(completed.stderr))

    def run(
        self,
        mode: str,
        commands: Sequence[tuple[str, Mapping[str, object]]],
        home: str | None = None,
    ) -> list[CommandResult]:
        if mode not in ALLOWLIST:
            raise ValidationError(f"unknown mode: {mode}")
        if not commands:
            raise ValidationError("no command was supplied")
        prepared = [validate_command(mode, cmd, args, home) for cmd, args in commands]

        with self._lock:
            if len(prepared) == 1 and not prepared[0].sensitive:
                argv = self._base_argv(mode) + ["/CMD", prepared[0].command, *prepared[0].tokens]
                return [self._call(argv, mode)]
            return self._run_batch(mode, prepared)

    def _run_batch(self, mode: str, prepared: Sequence[PreparedCommand]) -> list[CommandResult]:
        temp_dir = self._temp_dir()
        handle, path = tempfile.mkstemp(prefix="cmds-", suffix=".txt", dir=temp_dir)
        try:
            os.fchmod(handle, 0o600)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                for item in prepared:
                    stream.write(item.render())
                    stream.write("\n")
            argv = self._base_argv(mode) + [f"/IN:{path}"]
            overall = self._call(argv, mode)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

        blocks = split_command_blocks(overall.stdout)
        results: list[CommandResult] = []
        for index in range(len(prepared)):
            if index < len(blocks):
                block = blocks[index][1]
                match = ERROR_RE.search(block)
                if match:
                    code = int(match.group(1))
                elif overall.exit_code != 0 and not any(m in block for m in SUCCESS_MARKERS):
                    code = overall.exit_code
                else:
                    code = 0
                results.append(CommandResult(code, block, overall.stderr))
            else:
                results.append(CommandResult(overall.exit_code, "", overall.stderr))
        return results


def _decode(raw: bytes | None) -> str:
    if not raw:
        return ""
    return raw.decode("utf-8", "replace")


def execute(
    mode: str,
    commands: Sequence[tuple[str, Mapping[str, object]]],
    home: str | None = None,
    runner: VpncmdRunner | None = None,
) -> list[CommandResult]:
    return (runner or VpncmdRunner()).run(mode, commands, home)
