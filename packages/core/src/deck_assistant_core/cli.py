"""CLI profile and detection contracts.

This module only runs bounded read-only probes. It never reads provider
credential stores or starts login flows.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from deck_assistant_core.risk import ApprovalRequirement, RiskLevel, classify_command


class CliProfileError(ValueError):
    """Raised when a CLI profile or probe command is invalid."""


class CliProbeStatus(str, Enum):
    """Result of a local CLI availability probe."""

    MISSING = "missing"
    READY = "ready"
    PROBE_FAILED = "probe_failed"


class CliAuthState(str, Enum):
    """Credential state as reported by official CLI commands only."""

    CLI_MISSING = "cli_missing"
    LOGGED_IN = "logged_in"
    LOGGED_OUT = "logged_out"
    CHECK_FAILED = "check_failed"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class CliLaunchStatus(str, Enum):
    """Result of preparing a Terminal Mode launch argv."""

    READY = "ready"
    MISSING_EXECUTABLE = "missing_executable"


class CliSetupAction(str, Enum):
    """User-requested setup action for a built-in AI CLI."""

    INSTALL = "install"
    AUTH = "auth"
    INSTALL_AUTH = "install_auth"


class CliSetupStatus(str, Enum):
    """Result of preparing a setup action."""

    READY = "ready"
    UNSUPPORTED = "unsupported"
    MISSING_EXECUTABLE = "missing_executable"


class CliProfileHealthStatus(str, Enum):
    """Aggregate profile state for Decky UI/backend health views."""

    MISSING = "missing"
    READY = "ready"
    AUTH_UNKNOWN = "auth_unknown"
    LOGIN_REQUIRED = "login_required"
    CHECK_FAILED = "check_failed"
    UNKNOWN = "unknown"


class CliPermissionBypassStatus(str, Enum):
    """Result of preparing an unrestricted permission request."""

    AVAILABLE = "available"
    ENABLED = "enabled"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ProbeResult:
    """Captured result from a bounded read-only subprocess probe."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: str | None = None


def _validate_text_field(value: str, field_name: str) -> None:
    if not str(value).strip():
        raise CliProfileError(f"{field_name} must not be empty")


def _coerce_optional_argv(value: Sequence[str] | str | None, field_name: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    return _coerce_argv_parts(value, field_name)


def _coerce_argv_parts(
    parts: Sequence[str] | str,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if isinstance(parts, str):
        raise CliProfileError(f"{field_name} must use structured argv, not a shell string")

    normalized = tuple(str(part) for part in parts)
    if not normalized and not allow_empty:
        raise CliProfileError(f"{field_name} must not be empty")

    for index, part in enumerate(normalized):
        if not part.strip():
            raise CliProfileError(f"{field_name}[{index}] must not be empty")
    return normalized


@dataclass(frozen=True)
class CliProfile:
    """Known terminal profile for an executable owned by the user."""

    name: str
    display_name: str
    executable: str
    launch_args: tuple[str, ...] = ()
    version_args: tuple[str, ...] | None = ("--version",)
    auth_status_args: tuple[str, ...] | None = None
    auth_state_without_probe: CliAuthState = CliAuthState.UNKNOWN
    profile_type: str = "built_in"

    def __post_init__(self) -> None:
        _validate_text_field(self.name, "CLI profile name")
        _validate_text_field(self.display_name, "CLI profile display name")
        _validate_text_field(self.executable, "CLI profile executable")
        _coerce_argv_parts(self.launch_args, "CLI profile launch args", allow_empty=True)
        if self.version_args is not None:
            _coerce_argv_parts(self.version_args, "CLI profile version args")
        if self.auth_status_args is not None:
            _coerce_argv_parts(self.auth_status_args, "CLI profile auth status args")
        if self.profile_type not in {"built_in", "custom"}:
            raise CliProfileError(f"unsupported CLI profile type: {self.profile_type}")
        if self.profile_type == "custom":
            if self.version_args is not None:
                raise CliProfileError("custom CLI profiles must not define version probes")
            if self.auth_status_args is not None:
                raise CliProfileError("custom CLI profiles must not define auth status probes")
            if self.auth_state_without_probe is not CliAuthState.UNKNOWN:
                raise CliProfileError("custom CLI profiles must use an unknown auth state")

    @classmethod
    def from_custom_command(
        cls,
        *,
        name: str,
        display_name: str,
        argv: Sequence[str] | str,
    ) -> "CliProfile":
        """Create a custom terminal profile from structured argv only."""

        launch_argv = _coerce_argv_parts(argv, "custom CLI profile argv")
        return cls(
            name=name,
            display_name=display_name,
            executable=launch_argv[0],
            launch_args=launch_argv[1:],
            version_args=None,
            auth_status_args=None,
            auth_state_without_probe=CliAuthState.UNKNOWN,
            profile_type="custom",
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CliProfile":
        """Restore a CLI profile from serialized settings data."""

        profile_type = str(data.get("profile_type", "built_in"))
        if profile_type == "custom":
            if data.get("version_args") is not None:
                raise CliProfileError("custom CLI profiles must not define version probes")
            if data.get("auth_status_args") is not None:
                raise CliProfileError("custom CLI profiles must not define auth status probes")
            argv = data.get("argv")
            if argv is None:
                argv = [data["executable"], *data.get("launch_args", ())]
            return cls.from_custom_command(
                name=str(data["name"]),
                display_name=str(data["display_name"]),
                argv=argv,
            )

        name = str(data["name"])
        auth_state = _restored_auth_state_without_probe(data, profile_type, name)
        return cls(
            name=name,
            display_name=str(data["display_name"]),
            executable=str(data["executable"]),
            launch_args=_coerce_argv_parts(
                data.get("launch_args", ()),
                "CLI profile launch args",
                allow_empty=True,
            ),
            version_args=_coerce_optional_argv(data.get("version_args"), "CLI profile version args"),
            auth_status_args=_coerce_optional_argv(
                data.get("auth_status_args"),
                "CLI profile auth status args",
            ),
            auth_state_without_probe=auth_state,
            profile_type=profile_type,
        )

    def launch_argv(self, executable_path: str | None = None) -> tuple[str, ...]:
        """Return the argv used to start Terminal Mode for this profile."""

        return (executable_path or self.executable, *self.launch_args)

    def version_probe_argv(self, executable_path: str | None = None) -> tuple[str, ...] | None:
        """Return a read-only version probe argv, if the profile supports one."""

        if self.version_args is None:
            return None
        return (executable_path or self.executable, *self.version_args)

    def auth_status_probe_argv(self, executable_path: str | None = None) -> tuple[str, ...] | None:
        """Return a read-only auth status probe argv, if one is known."""

        if self.auth_status_args is None:
            return None
        return (executable_path or self.executable, *self.auth_status_args)

    @property
    def risk(self) -> RiskLevel:
        """Classify the launch command without executing it."""

        return _classify_terminal_launch(self, self.launch_argv())

    @property
    def approval_requirement(self) -> ApprovalRequirement:
        """Return the approval posture implied by the launch command risk."""

        return ApprovalRequirement.for_risk(self.risk)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "display_name": self.display_name,
            "profile_type": self.profile_type,
            "executable": self.executable,
            "launch_args": list(self.launch_args),
            "version_args": list(self.version_args) if self.version_args is not None else None,
            "auth_status_args": (
                list(self.auth_status_args) if self.auth_status_args is not None else None
            ),
            "auth_state_without_probe": self.auth_state_without_probe.value,
        }
        if self.profile_type == "custom":
            data["argv"] = list(self.launch_argv())
        return data


def _restored_auth_state_without_probe(
    data: Mapping[str, Any],
    profile_type: str,
    name: str,
) -> CliAuthState:
    """Resolve the auth state for a restored profile.

    When serialized data omits ``auth_state_without_probe`` for a known
    built-in profile (older settings, partial payloads), fall back to that
    profile's canonical default instead of a blanket UNKNOWN, which would
    mislabel profiles such as ``bash`` (NOT_APPLICABLE).
    """

    if "auth_state_without_probe" in data:
        return CliAuthState(str(data["auth_state_without_probe"]))

    if profile_type == "built_in":
        known = KNOWN_CLI_PROFILES.get(name.strip().lower())
        if known is not None:
            return known.auth_state_without_probe

    return CliAuthState.UNKNOWN


@dataclass(frozen=True)
class CliDetectionResult:
    """Availability and version result for a known CLI profile."""

    name: str
    display_name: str
    executable: str
    status: CliProbeStatus
    path: str | None = None
    version: str | None = None
    message: str = ""
    probe_argv: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "executable": self.executable,
            "status": self.status.value,
            "path": self.path,
            "version": self.version,
            "message": self.message,
            "probe_argv": list(self.probe_argv),
        }


@dataclass(frozen=True)
class CliAuthResult:
    """Auth state from a read-only official CLI status command."""

    name: str
    display_name: str
    executable: str
    state: CliAuthState
    path: str | None = None
    message: str = ""
    probe_argv: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "executable": self.executable,
            "state": self.state.value,
            "path": self.path,
            "message": self.message,
            "probe_argv": list(self.probe_argv),
        }


@dataclass(frozen=True)
class CliLaunchPlan:
    """Structured Terminal Mode launch plan; never starts the CLI."""

    name: str
    display_name: str
    profile_type: str
    executable: str
    status: CliLaunchStatus
    argv: tuple[str, ...]
    risk: RiskLevel
    approval_requirement: ApprovalRequirement
    path: str | None = None
    error: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "profile_type": self.profile_type,
            "executable": self.executable,
            "status": self.status.value,
            "path": self.path,
            "argv": list(self.argv),
            "risk": self.risk.value,
            "approval_requirement": self.approval_requirement.to_dict(),
            "error": self.error,
            "message": self.message,
        }


@dataclass(frozen=True)
class CliSetupPlan:
    """Structured setup plan for installing or authorizing a built-in CLI."""

    name: str
    display_name: str
    action: CliSetupAction
    status: CliSetupStatus
    argv: tuple[str, ...]
    risk: RiskLevel
    approval_requirement: ApprovalRequirement
    npm_package: str | None = None
    install_prefix: str | None = None
    bin_dir: str | None = None
    auth_argv: tuple[str, ...] = ()
    path: str | None = None
    error: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "action": self.action.value,
            "status": self.status.value,
            "argv": list(self.argv),
            "risk": self.risk.value,
            "approval_requirement": self.approval_requirement.to_dict(),
            "npm_package": self.npm_package,
            "install_prefix": self.install_prefix,
            "bin_dir": self.bin_dir,
            "auth_argv": list(self.auth_argv),
            "path": self.path,
            "error": self.error,
            "message": self.message,
        }

    def to_profile(self) -> "CliProfile":
        if self.status is not CliSetupStatus.READY:
            raise CliProfileError(self.error or "CLI setup plan is not ready")
        if not self.argv:
            raise CliProfileError("CLI setup plan argv must not be empty")
        return CliProfile(
            name=f"setup-{self.name}-{self.action.value}",
            display_name=f"{self.display_name} setup",
            executable=self.argv[0],
            launch_args=self.argv[1:],
            version_args=None,
            auth_status_args=None,
            auth_state_without_probe=CliAuthState.NOT_APPLICABLE,
            profile_type="built_in",
        )


@dataclass(frozen=True)
class CliProfileHealth:
    """Read-only aggregate health/status snapshot for one CLI profile."""

    name: str
    display_name: str
    profile_type: str
    status: CliProfileHealthStatus
    detection: CliDetectionResult
    auth: CliAuthResult
    launch_plan: CliLaunchPlan
    messages: tuple[str, ...] = ()

    @property
    def can_launch(self) -> bool:
        """Whether the executable is present and Terminal Mode can start it."""

        return self.launch_plan.status is CliLaunchStatus.READY

    @property
    def needs_login(self) -> bool:
        """Whether the official CLI auth probe reports login is required."""

        return self.auth.state is CliAuthState.LOGGED_OUT

    def to_dict(self) -> dict[str, Any]:
        launch_plan = self.launch_plan.to_dict()
        return {
            "name": self.name,
            "display_name": self.display_name,
            "profile_type": self.profile_type,
            "executable": self.launch_plan.executable,
            "status": self.status.value,
            "path": self.launch_plan.path or self.detection.path or self.auth.path,
            "version": self.detection.version,
            "auth_state": self.auth.state.value,
            "launch_status": self.launch_plan.status.value,
            "argv": launch_plan["argv"],
            "risk": self.launch_plan.risk.value,
            "approval_requirement": launch_plan["approval_requirement"],
            "can_launch": self.can_launch,
            "needs_login": self.needs_login,
            "messages": list(self.messages),
            "detection": self.detection.to_dict(),
            "auth": self.auth.to_dict(),
            "launch_plan": launch_plan,
        }


@dataclass(frozen=True)
class CliPermissionBypassPlan:
    """Safety posture for explicit CLI-native permission bypass requests."""

    name: str
    display_name: str
    status: CliPermissionBypassStatus
    risk: RiskLevel
    enabled: bool
    message: str
    bypass_args: tuple[str, ...] = ()

    @property
    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.for_risk(self.risk)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "status": self.status.value,
            "risk": self.risk.value,
            "enabled": self.enabled,
            "bypass_args": list(self.bypass_args),
            "approval_requirement": self.approval_requirement.to_dict(),
            "message": self.message,
        }


WhichFunc = Callable[[str], str | None]
ProbeRunner = Callable[[Sequence[str], float], ProbeResult]

_DECKY_EXECUTABLE_PATH_HINTS = (
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/home/deck/.local/bin",
    "/home/deck/bin",
)

_MANAGED_CLI_APP_DIR = "decky-ai-assistant"
_MANAGED_NPM_DIR = "npm"
_MANAGED_NODE_LINE = "22"
_MANAGED_WORKSPACES_DIR = "workspaces"

_CLI_SETUP_METADATA: Mapping[str, dict[str, Any]] = {
    "codex": {
        "npm_package": "@openai/codex",
        "auth_args": ("login",),
        "auth_message": "Starting the official Codex login flow.",
    },
    "claude": {
        "npm_package": "@anthropic-ai/claude-code",
        "auth_args": (),
        "auth_message": "Starting Claude Code; follow the official first-run login prompt.",
    },
}

_UNSAFE_SUBPROCESS_ENV_KEYS = (
    # Decky Loader and Steam runtime may expose compatibility libraries that
    # break read-only probes for system shells and CLIs.
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "LD_AUDIT",
    "LD_ORIGIN_PATH",
    "DYLD_LIBRARY_PATH",
    "DYLD_FALLBACK_LIBRARY_PATH",
    "DYLD_INSERT_LIBRARIES",
)


def resolve_executable(executable: str) -> str | None:
    """Resolve executables in Decky runtimes with minimal or unusual PATH values."""

    _validate_text_field(executable, "CLI executable")
    direct_match = shutil.which(executable)
    if direct_match is not None:
        return direct_match

    path_parts: list[str] = []
    for raw_part in os.environ.get("PATH", "").split(os.pathsep):
        part = raw_part.strip()
        if part and part not in path_parts:
            path_parts.append(part)

    for raw_part in (
        *managed_cli_bin_dirs(),
        *_DECKY_EXECUTABLE_PATH_HINTS,
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/bin"),
    ):
        part = raw_part.strip()
        if part and part not in path_parts:
            path_parts.append(part)

    if not path_parts:
        return None
    return shutil.which(executable, path=os.pathsep.join(path_parts))


def build_cli_probe_env(executable_path: str | None = None) -> dict[str, str]:
    """Build a read-only probe environment without Decky loader overrides."""

    env = dict(os.environ)
    for key in _UNSAFE_SUBPROCESS_ENV_KEYS:
        env.pop(key, None)

    path_parts: list[str] = []
    if executable_path:
        executable_dir = os.path.dirname(executable_path)
        if executable_dir:
            path_parts.append(executable_dir)
    for raw_part in (
        os.pathsep.join(managed_cli_bin_dirs()),
        env.get("PATH", ""),
        os.pathsep.join(_DECKY_EXECUTABLE_PATH_HINTS),
    ):
        for part in raw_part.split(os.pathsep):
            normalized = part.strip()
            if normalized and normalized not in path_parts:
                path_parts.append(normalized)
    env["PATH"] = os.pathsep.join(path_parts)
    env["TERM"] = "xterm-256color"
    env["HOME"] = managed_cli_user_home()
    env["XDG_DATA_HOME"] = os.path.dirname(managed_cli_data_dir())
    env["XDG_CONFIG_HOME"] = managed_cli_config_home()
    env["XDG_CACHE_HOME"] = managed_cli_cache_home()
    apply_managed_user_identity(env)
    return env


def apply_managed_user_identity(env: dict[str, str]) -> None:
    """Set USER/LOGNAME from the resolved ``HOME`` basename, never root's.

    The plugin may run under a root runtime while redirecting ``HOME`` to a
    real user home (``/home/deck`` or a custom ``DECKY_AI_ASSISTANT_CLI_HOME``).
    Deriving the account name from that resolved home keeps root's identity out
    of launched CLIs regardless of the configured home path. If the home cannot
    be mapped to a concrete account, fall back to ``deck`` rather than leaking
    an inherited root USER/LOGNAME.
    """

    account = _managed_user_name(env.get("HOME", ""))
    env["USER"] = account
    env["LOGNAME"] = account


def _managed_user_name(home: str) -> str:
    basename = os.path.basename(home.rstrip("/")) if home else ""
    if not basename or basename == "root":
        return "deck"
    return basename


def managed_cli_data_dir() -> str:
    """Return the user-local data directory used for managed CLI installs."""

    data_home = os.environ.get("XDG_DATA_HOME")
    home = managed_cli_user_home()
    if data_home and _should_replace_xdg_home(data_home, home):
        data_home = None
    if not data_home:
        data_home = os.path.join(home, ".local", "share")
    return os.path.join(data_home, _MANAGED_CLI_APP_DIR)


def managed_cli_data_dir_for_home(home: str) -> str:
    """Return the managed data directory for an explicit user home path."""

    if not _valid_home_path(home):
        raise CliProfileError("managed CLI home must be an absolute path")
    return os.path.join(home, ".local", "share", _MANAGED_CLI_APP_DIR)


def managed_cli_profile_workspace_dir(
    profile_name: str,
    *,
    home: str | None = None,
) -> str:
    """Return the stable user-local workspace directory for one CLI profile."""

    normalized = profile_name.strip().lower()
    if not normalized or not re.fullmatch(r"[a-z0-9._-]+", normalized):
        raise CliProfileError(f"invalid CLI profile workspace name: {profile_name}")

    data_dir = (
        managed_cli_data_dir_for_home(home)
        if home is not None
        else managed_cli_data_dir()
    )
    return os.path.join(data_dir, _MANAGED_WORKSPACES_DIR, normalized)


def managed_cli_user_home() -> str:
    """Return the home directory CLI children should use for auth stores."""

    override = os.environ.get("DECKY_AI_ASSISTANT_CLI_HOME")
    if override and _valid_home_path(override):
        return override

    home = os.environ.get("HOME", "")
    if _looks_like_root_runtime_home(home) and os.path.isdir("/home/deck"):
        return "/home/deck"
    if _valid_home_path(home):
        return home

    expanded_home = os.path.expanduser("~")
    if _looks_like_root_runtime_home(expanded_home) and os.path.isdir("/home/deck"):
        return "/home/deck"
    if _valid_home_path(expanded_home):
        return expanded_home

    if os.path.isdir("/home/deck"):
        return "/home/deck"
    return os.getcwd()


def managed_cli_config_home() -> str:
    """Return the config home CLI children should use for provider settings."""

    home = managed_cli_user_home()
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home and not _should_replace_xdg_home(config_home, home):
        return config_home
    return os.path.join(home, ".config")


def managed_cli_cache_home() -> str:
    """Return the cache home CLI children should use for provider caches."""

    home = managed_cli_user_home()
    cache_home = os.environ.get("XDG_CACHE_HOME")
    if cache_home and not _should_replace_xdg_home(cache_home, home):
        return cache_home
    return os.path.join(home, ".cache")


def managed_cli_npm_prefix() -> str:
    """Return the npm prefix used for user-local CLI installs."""

    return os.path.join(managed_cli_data_dir(), _MANAGED_NPM_DIR)


def managed_cli_npm_bin_dir() -> str:
    """Return the npm .bin directory containing managed CLI executables."""

    return os.path.join(managed_cli_npm_prefix(), "node_modules", ".bin")


def managed_cli_node_bin_dirs() -> tuple[str, ...]:
    """Return discovered user-local Node.js bin directories for managed CLIs."""

    node_root = os.path.join(managed_cli_data_dir(), "node")
    if not os.path.isdir(node_root):
        return ()

    try:
        entries = os.listdir(node_root)
    except OSError:
        return ()

    candidates: list[tuple[tuple[int, int, int, str], str]] = []
    for entry in entries:
        bin_dir = os.path.join(node_root, entry, "bin")
        node_path = os.path.join(bin_dir, "node")
        if not os.path.isfile(node_path) or not os.access(node_path, os.X_OK):
            continue
        candidates.append((_node_version_sort_key(entry), bin_dir))

    return tuple(bin_dir for _, bin_dir in sorted(candidates, reverse=True))


def managed_cli_bin_dirs() -> tuple[str, ...]:
    """Return user-local CLI bin directories preferred by Decky Terminal Mode."""

    return (
        managed_cli_npm_bin_dir(),
        *managed_cli_node_bin_dirs(),
        os.path.join(managed_cli_user_home(), ".local", "bin"),
        os.path.join(managed_cli_user_home(), "bin"),
    )


def _valid_home_path(value: str) -> bool:
    path = value.strip()
    return bool(path) and path != "/" and os.path.isabs(path)


def _looks_like_root_runtime_home(value: str) -> bool:
    path = value.strip()
    return path in {"", "/", "/root"}


def _should_replace_xdg_home(value: str, home: str) -> bool:
    path = os.path.abspath(os.path.expanduser(value))
    normalized_home = os.path.abspath(os.path.expanduser(home))
    if _looks_like_root_runtime_home(normalized_home):
        return False
    return path == "/root" or path.startswith("/root/")


def _node_version_sort_key(value: str) -> tuple[int, int, int, str]:
    match = re.match(r"node-v(\d+)[.](\d+)[.](\d+)-", value)
    if match:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)), value)
    return (0, 0, 0, value)


KNOWN_CLI_PROFILES: Mapping[str, CliProfile] = {
    "bash": CliProfile(
        name="bash",
        display_name="Bash",
        executable="bash",
        auth_state_without_probe=CliAuthState.NOT_APPLICABLE,
    ),
    "codex": CliProfile(
        name="codex",
        display_name="Codex CLI",
        executable="codex",
        auth_status_args=("login", "status"),
    ),
    "claude": CliProfile(
        name="claude",
        display_name="Claude Code",
        executable="claude",
    ),
}

CLI_PERMISSION_BYPASS_ARGS: Mapping[str, tuple[str, ...]] = {
    "codex": ("--dangerously-bypass-approvals-and-sandbox",),
    "claude": ("--permission-mode", "bypassPermissions"),
}


def list_cli_profiles() -> tuple[CliProfile, ...]:
    """Return known built-in CLI profiles in stable order."""

    return tuple(KNOWN_CLI_PROFILES[name] for name in sorted(KNOWN_CLI_PROFILES))


def get_cli_profile(name: str) -> CliProfile:
    """Return one known CLI profile by name."""

    normalized = name.strip().lower()
    try:
        return KNOWN_CLI_PROFILES[normalized]
    except KeyError as exc:
        raise CliProfileError(f"unknown CLI profile: {name}") from exc


def plan_cli_launch(
    profile: str | CliProfile,
    *,
    which: WhichFunc = resolve_executable,
) -> CliLaunchPlan:
    """Prepare a structured Terminal Mode launch argv without executing it."""

    cli_profile = get_cli_profile(profile) if isinstance(profile, str) else profile
    path = which(cli_profile.executable)

    if path is None:
        argv = cli_profile.launch_argv()
        risk = _classify_terminal_launch(cli_profile, argv)
        error = f"{cli_profile.executable} was not found on PATH."
        return CliLaunchPlan(
            name=cli_profile.name,
            display_name=cli_profile.display_name,
            profile_type=cli_profile.profile_type,
            executable=cli_profile.executable,
            status=CliLaunchStatus.MISSING_EXECUTABLE,
            argv=argv,
            risk=risk,
            approval_requirement=ApprovalRequirement.for_risk(risk),
            error=error,
            message="Executable is missing; Terminal Mode must not start this profile.",
        )

    argv = cli_profile.launch_argv(path)
    risk = _classify_terminal_launch(cli_profile, argv)
    return CliLaunchPlan(
        name=cli_profile.name,
        display_name=cli_profile.display_name,
        profile_type=cli_profile.profile_type,
        executable=cli_profile.executable,
        status=CliLaunchStatus.READY,
        path=path,
        argv=argv,
        risk=risk,
        approval_requirement=ApprovalRequirement.for_risk(risk),
        message="CLI launch argv is ready.",
    )


def plan_cli_setup_action(
    profile: str | CliProfile,
    action: str | CliSetupAction,
    *,
    which: WhichFunc = resolve_executable,
) -> CliSetupPlan:
    """Prepare a user-requested install/auth action without starting it."""

    cli_profile = get_cli_profile(profile) if isinstance(profile, str) else profile
    setup_action = CliSetupAction(action)
    metadata = _CLI_SETUP_METADATA.get(cli_profile.name)
    if metadata is None or cli_profile.profile_type != "built_in":
        return _unsupported_setup_plan(cli_profile, setup_action)

    if setup_action is CliSetupAction.AUTH:
        return _auth_setup_plan(cli_profile, metadata, which=which)
    return _install_setup_plan(cli_profile, setup_action, metadata)


def summarize_cli_profile_health(
    profile: str | CliProfile,
    *,
    timeout_seconds: float = 2.0,
    which: WhichFunc = resolve_executable,
    run_probe: ProbeRunner | None = None,
) -> CliProfileHealth:
    """Return an aggregate read-only health snapshot for a CLI profile.

    Built-in profiles are checked through the existing detection, auth, and
    launch contracts. Custom profiles keep structured argv-only launch planning
    and do not define version or auth probes.
    """

    _validate_timeout(timeout_seconds)
    cli_profile = get_cli_profile(profile) if isinstance(profile, str) else profile
    cached_which = _cached_which(which)

    launch_plan = plan_cli_launch(cli_profile, which=cached_which)
    if cli_profile.profile_type == "built_in":
        detection = detect_cli(
            cli_profile.name,
            timeout_seconds=timeout_seconds,
            which=cached_which,
            run_probe=run_probe,
        )
        auth = check_cli_auth(
            cli_profile.name,
            timeout_seconds=timeout_seconds,
            which=cached_which,
            run_probe=run_probe,
        )
    else:
        detection = _custom_profile_detection(cli_profile, launch_plan)
        auth = _custom_profile_auth(cli_profile, launch_plan)

    return CliProfileHealth(
        name=cli_profile.name,
        display_name=cli_profile.display_name,
        profile_type=cli_profile.profile_type,
        status=_aggregate_cli_health_status(detection, auth, launch_plan),
        detection=detection,
        auth=auth,
        launch_plan=launch_plan,
        messages=_collect_cli_health_messages(detection, auth, launch_plan),
    )


def apply_cli_permission_bypass(profile: str | CliProfile) -> CliProfile:
    """Return a launch profile with target-native permission-bypass args.

    Custom profiles do not have a known native permission mode; callers can
    still treat them as trusted at the Decky launch gate, but their argv is not
    rewritten here.
    """

    cli_profile = get_cli_profile(profile) if isinstance(profile, str) else profile
    bypass_args = CLI_PERMISSION_BYPASS_ARGS.get(cli_profile.name)
    if not bypass_args:
        return cli_profile
    return replace(cli_profile, launch_args=(*bypass_args, *cli_profile.launch_args))


def plan_cli_permission_bypass(
    profile: str | CliProfile,
    *,
    enabled: bool = False,
) -> CliPermissionBypassPlan:
    """Return the explicit permission-bypass plan for one CLI profile."""

    cli_profile = get_cli_profile(profile) if isinstance(profile, str) else profile
    bypass_args = CLI_PERMISSION_BYPASS_ARGS.get(cli_profile.name, ())
    if bypass_args:
        status = CliPermissionBypassStatus.ENABLED if enabled else CliPermissionBypassStatus.AVAILABLE
        message = (
            "Starts this CLI with its native no-approval permission mode. "
            "Existing running sessions must be restarted before the setting takes effect."
        )
    elif cli_profile.profile_type == "custom":
        status = CliPermissionBypassStatus.ENABLED if enabled else CliPermissionBypassStatus.AVAILABLE
        message = (
            "Custom profiles have no built-in bypass args. When enabled, Decky trusts "
            "this profile's configured argv and will not block launch because of command risk."
        )
    else:
        status = CliPermissionBypassStatus.UNSUPPORTED
        message = "This profile does not support a known CLI-native permission bypass mode."

    return CliPermissionBypassPlan(
        name=cli_profile.name,
        display_name=cli_profile.display_name,
        status=status,
        risk=RiskLevel.DANGER,
        enabled=enabled,
        bypass_args=bypass_args,
        message=message,
    )


def detect_cli(
    name: str,
    *,
    timeout_seconds: float = 2.0,
    which: WhichFunc = resolve_executable,
    run_probe: ProbeRunner | None = None,
) -> CliDetectionResult:
    """Detect whether a known CLI exists and can answer a read-only version probe."""

    _validate_timeout(timeout_seconds)
    profile = get_cli_profile(name)
    path = which(profile.executable)

    if path is None:
        return CliDetectionResult(
            name=profile.name,
            display_name=profile.display_name,
            executable=profile.executable,
            status=CliProbeStatus.MISSING,
            message=f"{profile.executable} was not found on PATH.",
        )

    probe_argv = profile.version_probe_argv(path)
    if probe_argv is None:
        return CliDetectionResult(
            name=profile.name,
            display_name=profile.display_name,
            executable=profile.executable,
            status=CliProbeStatus.READY,
            path=path,
            message="CLI was found; no version probe is defined.",
        )

    _validate_read_only_probe(probe_argv)
    runner = run_probe or _run_probe
    result = runner(probe_argv, timeout_seconds)

    if result.returncode == 0 and not result.timed_out and result.error is None:
        version = _first_output_line(result.stdout) or _first_output_line(result.stderr)
        return CliDetectionResult(
            name=profile.name,
            display_name=profile.display_name,
            executable=profile.executable,
            status=CliProbeStatus.READY,
            path=path,
            version=version,
            message="CLI is available.",
            probe_argv=tuple(probe_argv),
        )

    return CliDetectionResult(
        name=profile.name,
        display_name=profile.display_name,
        executable=profile.executable,
        status=CliProbeStatus.PROBE_FAILED,
        path=path,
        message=_probe_failure_message(result),
        probe_argv=tuple(probe_argv),
    )


def check_cli_auth(
    name: str,
    *,
    timeout_seconds: float = 2.0,
    which: WhichFunc = resolve_executable,
    run_probe: ProbeRunner | None = None,
) -> CliAuthResult:
    """Check auth status without reading token files or provider credential stores."""

    _validate_timeout(timeout_seconds)
    profile = get_cli_profile(name)
    path = which(profile.executable)

    if path is None:
        return CliAuthResult(
            name=profile.name,
            display_name=profile.display_name,
            executable=profile.executable,
            state=CliAuthState.CLI_MISSING,
            message=f"{profile.executable} was not found on PATH.",
        )

    probe_argv = profile.auth_status_probe_argv(path)
    if probe_argv is None:
        return CliAuthResult(
            name=profile.name,
            display_name=profile.display_name,
            executable=profile.executable,
            state=profile.auth_state_without_probe,
            path=path,
            message="No read-only auth status probe is defined for this profile.",
        )

    _validate_read_only_probe(probe_argv)
    runner = run_probe or _run_probe
    result = runner(probe_argv, timeout_seconds)

    if result.returncode == 0 and not result.timed_out and result.error is None:
        return CliAuthResult(
            name=profile.name,
            display_name=profile.display_name,
            executable=profile.executable,
            state=CliAuthState.LOGGED_IN,
            path=path,
            message="CLI reports an authenticated session.",
            probe_argv=tuple(probe_argv),
        )

    output = f"{result.stdout}\n{result.stderr}".lower()
    if any(marker in output for marker in _LOGGED_OUT_MARKERS):
        state = CliAuthState.LOGGED_OUT
        message = "CLI reports that login is required."
    else:
        state = CliAuthState.CHECK_FAILED
        message = _probe_failure_message(result)

    return CliAuthResult(
        name=profile.name,
        display_name=profile.display_name,
        executable=profile.executable,
        state=state,
        path=path,
        message=message,
        probe_argv=tuple(probe_argv),
    )


_LOGGED_OUT_MARKERS = (
    "login required",
    "not authenticated",
    "not logged in",
    "please log in",
    "unauthorized",
)


def _unsupported_setup_plan(profile: CliProfile, action: CliSetupAction) -> CliSetupPlan:
    risk = RiskLevel.READ_ONLY
    return CliSetupPlan(
        name=profile.name,
        display_name=profile.display_name,
        action=action,
        status=CliSetupStatus.UNSUPPORTED,
        argv=(),
        risk=risk,
        approval_requirement=ApprovalRequirement.for_risk(risk),
        error=f"{profile.display_name} does not support managed setup.",
        message="Managed setup is available only for built-in Codex and Claude profiles.",
    )


def _auth_setup_plan(
    profile: CliProfile,
    metadata: Mapping[str, Any],
    *,
    which: WhichFunc,
) -> CliSetupPlan:
    path = which(profile.executable)
    auth_args = tuple(str(part) for part in metadata.get("auth_args", ()))
    auth_argv = (path or profile.executable, *auth_args)
    risk = RiskLevel.LOW_WRITE

    if path is None:
        return CliSetupPlan(
            name=profile.name,
            display_name=profile.display_name,
            action=CliSetupAction.AUTH,
            status=CliSetupStatus.MISSING_EXECUTABLE,
            argv=auth_argv,
            risk=risk,
            approval_requirement=ApprovalRequirement.for_risk(risk),
            npm_package=str(metadata.get("npm_package", "")) or None,
            install_prefix=managed_cli_npm_prefix(),
            bin_dir=managed_cli_npm_bin_dir(),
            auth_argv=auth_argv,
            error=f"{profile.executable} was not found on PATH.",
            message="Install the latest CLI before starting its official auth flow.",
        )

    return CliSetupPlan(
        name=profile.name,
        display_name=profile.display_name,
        action=CliSetupAction.AUTH,
        status=CliSetupStatus.READY,
        argv=auth_argv,
        risk=risk,
        approval_requirement=ApprovalRequirement.for_risk(risk),
        npm_package=str(metadata.get("npm_package", "")) or None,
        install_prefix=managed_cli_npm_prefix(),
        bin_dir=managed_cli_npm_bin_dir(),
        auth_argv=auth_argv,
        path=path,
        message=str(metadata.get("auth_message") or "Starting the official CLI auth flow."),
    )


def _install_setup_plan(
    profile: CliProfile,
    action: CliSetupAction,
    metadata: Mapping[str, Any],
) -> CliSetupPlan:
    package_name = str(metadata.get("npm_package") or "")
    if not package_name:
        return _unsupported_setup_plan(profile, action)

    auth_args = tuple(str(part) for part in metadata.get("auth_args", ()))
    script = _build_npm_setup_script(
        profile=profile,
        package_name=package_name,
        action=action,
        auth_args=auth_args,
        auth_message=str(metadata.get("auth_message") or "Starting the official CLI auth flow."),
    )
    argv = ("bash", "-lc", script)
    risk = RiskLevel.LOW_WRITE
    auth_argv = (profile.executable, *auth_args)
    return CliSetupPlan(
        name=profile.name,
        display_name=profile.display_name,
        action=action,
        status=CliSetupStatus.READY,
        argv=argv,
        risk=risk,
        approval_requirement=ApprovalRequirement.for_risk(risk),
        npm_package=package_name,
        install_prefix=managed_cli_npm_prefix(),
        bin_dir=managed_cli_npm_bin_dir(),
        auth_argv=auth_argv,
        message=(
            f"Install latest {package_name} into the plugin user-local npm prefix."
            if action is CliSetupAction.INSTALL
            else f"Install latest {package_name}, then start the official auth flow."
        ),
    )


# Static shell function: prepend any already-downloaded managed Node.js bins to
# PATH so a previously bootstrapped runtime is reused before any fresh download.
_SETUP_FN_PREPEND_NODE_BINS = (
    "prepend_existing_managed_node_bins() {",
    '  for managed_node_bin in "$node_root"/node-v*/bin; do',
    '    if [ -x "$managed_node_bin/node" ]; then',
    '      PATH="$managed_node_bin:$PATH"',
    "    fi",
    "  done",
    "  export PATH",
    "}",
)

# Static shell function: download a URL to a path using curl, falling back to
# wget, and failing loudly when neither downloader is available.
_SETUP_FN_DOWNLOAD_FILE = (
    "download_file() {",
    '  url="$1"',
    '  output="$2"',
    "  if command -v curl >/dev/null 2>&1; then",
    '    curl -fL "$url" -o "$output"',
    "  elif command -v wget >/dev/null 2>&1; then",
    '    wget -O "$output" "$url"',
    "  else",
    '    echo "curl or wget is required to download Node.js when npm is missing."',
    "    exit 127",
    "  fi",
    "}",
)

# Static shell function: ensure npm exists, bootstrapping a verified user-local
# Node.js release from nodejs.org (with SHA-256 checks) when it is missing.
_SETUP_FN_ENSURE_NPM = (
    "ensure_npm() {",
    "  if command -v npm >/dev/null 2>&1; then",
    "    return",
    "  fi",
    '  echo "npm was not found. Installing user-local Node.js $node_line from nodejs.org."',
    '  case "$(uname -s)" in',
    '    Linux) node_os="linux" ;;',
    '    *) echo "Unsupported OS for automatic Node.js bootstrap: $(uname -s)"; exit 127 ;;',
    "  esac",
    '  case "$(uname -m)" in',
    '    x86_64|amd64) node_arch="x64" ;;',
    '    aarch64|arm64) node_arch="arm64" ;;',
    '    *) echo "Unsupported CPU for automatic Node.js bootstrap: $(uname -m)"; exit 127 ;;',
    "  esac",
    '  tmp_dir="$prefix/.tmp-node"',
    '  mkdir -p "$tmp_dir" "$node_root"',
    '  sums_url="https://nodejs.org/download/release/latest-v${node_line}.x/SHASUMS256.txt"',
    '  sums_file="$tmp_dir/SHASUMS256.txt"',
    '  download_file "$sums_url" "$sums_file"',
    '  tarball="$(awk -v os="$node_os" -v arch="$node_arch" '
    + "'$2 ~ \"node-v.*-\" os \"-\" arch \"[.]tar[.]xz$\" {print $2; exit}' "
    + '"$sums_file")"',
    '  if [ -z "$tarball" ]; then',
    '    echo "Could not find a Node.js tarball for $node_os-$node_arch."',
    "    exit 127",
    "  fi",
    '  expected_sha="$(awk -v file="$tarball" ' + "'$2 == file {print $1; exit}' " + '"$sums_file")"',
    '  tarball_path="$tmp_dir/$tarball"',
    '  download_file "https://nodejs.org/download/release/latest-v${node_line}.x/$tarball" "$tarball_path"',
    "  if command -v sha256sum >/dev/null 2>&1; then",
    '    actual_sha="$(sha256sum "$tarball_path" | awk ' + "'{print $1}'" + ')"',
    '    if [ "$actual_sha" != "$expected_sha" ]; then',
    '      echo "Node.js download checksum mismatch."',
    "      exit 127",
    "    fi",
    "  else",
    '    echo "sha256sum was not found; continuing without local checksum verification."',
    "  fi",
    '  node_extract_dir="$node_root/${tarball%.tar.xz}"',
    '  if [ ! -x "$node_extract_dir/bin/npm" ]; then',
    '    mkdir -p "$node_extract_dir"',
    '    tar -xJf "$tarball_path" -C "$node_extract_dir" --strip-components=1',
    "  fi",
    '  export PATH="$node_extract_dir/bin:$PATH"',
    "  if ! command -v npm >/dev/null 2>&1; then",
    '    echo "Node.js bootstrap finished, but npm is still unavailable."',
    "    exit 127",
    "  fi",
    "}",
)

# Static install body: bootstrap npm, install the package, and verify the
# managed executable landed in the expected bin dir.
_SETUP_INSTALL_BODY = (
    'echo "Decky AI Assistant setup: $display_name"',
    'echo "Install prefix: $prefix"',
    'echo "Managed bin dir: $bin_dir"',
    'mkdir -p "$prefix"',
    "prepend_existing_managed_node_bins",
    "ensure_npm",
    'echo "Installing latest package: $package"',
    'npm install --prefix "$prefix" "$package"',
    'echo ""',
    'echo "Installed package versions:"',
    'npm list --prefix "$prefix" --depth=0 || true',
    'echo ""',
    'if [ ! -x "$managed_executable" ]; then',
    '  echo "Install finished, but executable $executable was not found in $bin_dir."',
    "  exit 127",
    "fi",
    '"$managed_executable" --version || true',
)


def _npm_setup_preamble(
    *,
    package_name: str,
    executable: str,
    display_name: str,
) -> list[str]:
    """Return the dynamic variable preamble for the managed npm setup script."""

    return [
        "set -euo pipefail",
        'data_home="${XDG_DATA_HOME:-$HOME/.local/share}"',
        f"prefix=\"$data_home/{_MANAGED_CLI_APP_DIR}/{_MANAGED_NPM_DIR}\"",
        f"node_line=\"${{DECKY_AI_ASSISTANT_NODE_LINE:-{_MANAGED_NODE_LINE}}}\"",
        f"node_root=\"$data_home/{_MANAGED_CLI_APP_DIR}/node\"",
        f"package={shlex.quote(f'{package_name}@latest')}",
        f"executable={shlex.quote(executable)}",
        f"display_name={shlex.quote(display_name)}",
        'bin_dir="$prefix/node_modules/.bin"',
        'managed_executable="$bin_dir/$executable"',
        'export PATH="$bin_dir:${PATH:-}:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:$HOME/bin"',
    ]


def _npm_setup_epilogue(
    *,
    action: CliSetupAction,
    auth_args: tuple[str, ...],
    auth_message: str,
) -> list[str]:
    """Return the trailing lines that either start the auth flow or stop here."""

    if action is CliSetupAction.INSTALL_AUTH:
        quoted_auth_args = " ".join(shlex.quote(part) for part in auth_args)
        return [
            'echo ""',
            f"echo {shlex.quote(auth_message)}",
            f'exec "$managed_executable" {quoted_auth_args}'.rstrip(),
        ]
    return [
        'echo ""',
        'echo "Install complete. Start the auth flow from Settings when needed."',
    ]


def _build_npm_setup_script(
    *,
    profile: CliProfile,
    package_name: str,
    action: CliSetupAction,
    auth_args: tuple[str, ...],
    auth_message: str,
) -> str:
    lines = [
        *_npm_setup_preamble(
            package_name=package_name,
            executable=profile.executable,
            display_name=profile.display_name,
        ),
        *_SETUP_FN_PREPEND_NODE_BINS,
        *_SETUP_FN_DOWNLOAD_FILE,
        *_SETUP_FN_ENSURE_NPM,
        *_SETUP_INSTALL_BODY,
        *_npm_setup_epilogue(
            action=action,
            auth_args=auth_args,
            auth_message=auth_message,
        ),
    ]
    return "\n".join(lines)


def _cached_which(which: WhichFunc) -> WhichFunc:
    cache: dict[str, str | None] = {}

    def cached(executable: str) -> str | None:
        if executable not in cache:
            cache[executable] = which(executable)
        return cache[executable]

    return cached


def _custom_profile_detection(
    profile: CliProfile,
    launch_plan: CliLaunchPlan,
) -> CliDetectionResult:
    if launch_plan.status is CliLaunchStatus.MISSING_EXECUTABLE:
        return CliDetectionResult(
            name=profile.name,
            display_name=profile.display_name,
            executable=profile.executable,
            status=CliProbeStatus.MISSING,
            message=f"{profile.executable} was not found on PATH.",
        )

    return CliDetectionResult(
        name=profile.name,
        display_name=profile.display_name,
        executable=profile.executable,
        status=CliProbeStatus.READY,
        path=launch_plan.path,
        message="CLI was found; custom profiles do not define version probes.",
    )


def _custom_profile_auth(profile: CliProfile, launch_plan: CliLaunchPlan) -> CliAuthResult:
    if launch_plan.status is CliLaunchStatus.MISSING_EXECUTABLE:
        return CliAuthResult(
            name=profile.name,
            display_name=profile.display_name,
            executable=profile.executable,
            state=CliAuthState.CLI_MISSING,
            message=f"{profile.executable} was not found on PATH.",
        )

    return CliAuthResult(
        name=profile.name,
        display_name=profile.display_name,
        executable=profile.executable,
        state=CliAuthState.NOT_APPLICABLE,
        path=launch_plan.path,
        message="Auth status is not applicable for custom terminal profiles.",
    )


def _classify_terminal_launch(profile: CliProfile, argv: Sequence[str]) -> RiskLevel:
    """Classify starting a Terminal Mode profile, not commands typed inside it."""

    if profile.profile_type == "built_in" and not profile.launch_args:
        return RiskLevel.READ_ONLY

    bypass = CLI_PERMISSION_BYPASS_ARGS.get(profile.name)
    if (
        profile.profile_type == "built_in"
        and bypass
        and tuple(profile.launch_args[: len(bypass)]) == bypass
    ):
        return RiskLevel.DANGER
    return classify_command(argv)


def _aggregate_cli_health_status(
    detection: CliDetectionResult,
    auth: CliAuthResult,
    launch_plan: CliLaunchPlan,
) -> CliProfileHealthStatus:
    if (
        launch_plan.status is CliLaunchStatus.MISSING_EXECUTABLE
        or detection.status is CliProbeStatus.MISSING
        or auth.state is CliAuthState.CLI_MISSING
    ):
        return CliProfileHealthStatus.MISSING
    if auth.state is CliAuthState.LOGGED_OUT:
        return CliProfileHealthStatus.LOGIN_REQUIRED
    if detection.status is CliProbeStatus.PROBE_FAILED or auth.state is CliAuthState.CHECK_FAILED:
        return CliProfileHealthStatus.CHECK_FAILED
    if auth.state is CliAuthState.UNKNOWN:
        return CliProfileHealthStatus.AUTH_UNKNOWN
    if launch_plan.status is CliLaunchStatus.READY and detection.status is CliProbeStatus.READY:
        return CliProfileHealthStatus.READY
    return CliProfileHealthStatus.UNKNOWN


def _collect_cli_health_messages(
    detection: CliDetectionResult,
    auth: CliAuthResult,
    launch_plan: CliLaunchPlan,
) -> tuple[str, ...]:
    messages: list[str] = []
    seen: set[str] = set()
    for message in (
        detection.message,
        auth.message,
        launch_plan.error or "",
        launch_plan.message,
    ):
        if message and message not in seen:
            seen.add(message)
            messages.append(message)
    return tuple(messages)


def _validate_timeout(timeout_seconds: float) -> None:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")


def _validate_read_only_probe(argv: Sequence[str]) -> None:
    risk = classify_command(argv)
    if risk is not RiskLevel.READ_ONLY:
        rendered = " ".join(str(part) for part in argv)
        raise CliProfileError(f"probe command must be read_only: {rendered}")


def _run_probe(argv: Sequence[str], timeout_seconds: float) -> ProbeResult:
    try:
        completed = subprocess.run(
            tuple(argv),
            capture_output=True,
            check=False,
            env=build_cli_probe_env(str(argv[0]) if argv else None),
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(returncode=124, timed_out=True)
    except OSError as exc:
        return ProbeResult(returncode=127, error=str(exc))

    return ProbeResult(
        returncode=completed.returncode,
        stdout=completed.stdout[:4096],
        stderr=completed.stderr[:4096],
    )


def _first_output_line(output: str) -> str | None:
    for line in output.splitlines():
        cleaned = " ".join(line.strip().split())
        if cleaned:
            return cleaned[:200]
    return None


def _probe_failure_message(result: ProbeResult) -> str:
    if result.timed_out:
        return "Read-only CLI probe timed out."
    if result.error:
        return "Read-only CLI probe could not start."
    return f"Read-only CLI probe exited with status {result.returncode}."
