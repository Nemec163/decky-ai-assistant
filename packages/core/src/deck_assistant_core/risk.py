"""Risk classification primitives for local Deck actions.

Risk is informational metadata for UI and CLI context. CLI sessions use these
labels for display only.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum


class RiskLevel(str, Enum):
    """Ordered local action risk levels."""

    READ_ONLY = "read_only"
    LOW_WRITE = "low_write"
    HIGH_WRITE = "high_write"
    DANGER = "danger"


_RISK_ORDER = {
    RiskLevel.READ_ONLY: 0,
    RiskLevel.LOW_WRITE: 1,
    RiskLevel.HIGH_WRITE: 2,
    RiskLevel.DANGER: 3,
}


_READ_ONLY_COMMANDS = {
    "awk",
    "basename",
    "cat",
    "cut",
    "df",
    "diff",
    "dirname",
    "du",
    "echo",
    "env",
    "file",
    "find",
    "grep",
    "head",
    "id",
    "journalctl",
    "less",
    "ls",
    "printf",
    "pwd",
    "rg",
    "sed",
    "sort",
    "stat",
    "tail",
    "uname",
    "wc",
    "which",
    "whoami",
}

_LOW_WRITE_COMMANDS = {
    "install",
    "mkdir",
    "sqlite3",
    "tee",
    "touch",
}

_HIGH_WRITE_COMMANDS = {
    "cp",
    "git",
    "mv",
    "rsync",
    "steam",
}

_DANGER_COMMANDS = {
    "chmod",
    "chown",
    "dd",
    "doas",
    "mkfs",
    "mount",
    "pacman",
    "pkexec",
    "rm",
    "rmdir",
    "shred",
    "steamos-readonly",
    "sudo",
    "systemctl",
    "umount",
    "unlink",
}

_SHELL_EXECUTORS = {"bash", "dash", "fish", "sh", "zsh"}

_SYSTEM_PATH_PREFIXES = (
    "/boot",
    "/dev",
    "/etc",
    "/proc",
    "/run",
    "/sys",
    "/usr",
    "/var/lib/pacman",
)

_HIGH_WRITE_PATH_MARKERS = (
    "/.config/flatpak",
    "/.local/share/flatpak",
    "/.local/share/steam",
    "/.steam",
    "/.var/app",
    "/compatdata",
    "/shadercache",
    "/steamapps",
)


def max_risk(*levels: RiskLevel) -> RiskLevel:
    """Return the highest risk level from one or more values."""

    if not levels:
        return RiskLevel.READ_ONLY
    return max(levels, key=lambda level: _RISK_ORDER[level])


def classify_command(argv: Sequence[str] | str) -> RiskLevel:
    """Classify a structured command without executing it.

    Shell command strings and shell executors are classified as danger because
    they hide the actual operation from display metadata.
    """

    if isinstance(argv, str):
        return RiskLevel.DANGER
    if not argv:
        raise ValueError("command argv must not be empty")

    executable = _basename(argv[0]).lower()
    args = [part.lower() for part in argv[1:]]

    if executable in _SHELL_EXECUTORS:
        return _classify_shell_executor(args)
    if executable in _DANGER_COMMANDS:
        return RiskLevel.DANGER
    if executable == "env" and args:
        return _classify_env(argv[1:])
    if executable in {"python", "python3"}:
        return _classify_python(args)
    if executable == "find" and any(
        arg in {"-delete", "-exec", "-execdir", "-ok", "-okdir"} for arg in args
    ):
        return RiskLevel.DANGER
    if executable == "sed" and any(arg.startswith("-i") for arg in args):
        return RiskLevel.HIGH_WRITE
    if executable == "journalctl" and any(arg.startswith("--vacuum") for arg in args):
        return RiskLevel.DANGER
    if executable in {"curl", "wget"}:
        return _classify_download(executable, argv)
    if executable == "flatpak":
        return _classify_flatpak(args)
    if executable == "git":
        return _classify_git(args)
    if executable in {"codex", "claude"}:
        return _classify_ai_cli(executable, args)
    if executable in _READ_ONLY_COMMANDS:
        return RiskLevel.READ_ONLY
    if executable in _LOW_WRITE_COMMANDS:
        return RiskLevel.LOW_WRITE
    # Known high-write commands and unknown executables both classify as
    # high_write; opaque commands must never default below high_write.
    return RiskLevel.HIGH_WRITE


def classify_file_edit(path: str, operation: str, *, temporary: bool = False) -> RiskLevel:
    """Classify a proposed file operation."""

    normalized = _normalize_path(path)
    op = operation.lower()

    if op in {"read", "inspect"}:
        return RiskLevel.READ_ONLY
    if op in {"delete", "remove", "unlink"} and not temporary:
        return RiskLevel.DANGER
    if normalized.startswith(_SYSTEM_PATH_PREFIXES):
        return RiskLevel.DANGER
    if any(marker in normalized for marker in _HIGH_WRITE_PATH_MARKERS):
        return RiskLevel.HIGH_WRITE
    if op in {"create", "modify", "write", "append", "delete", "remove", "unlink"}:
        return RiskLevel.LOW_WRITE
    raise ValueError(f"unknown file operation: {operation}")


def _classify_download(executable: str, argv: Sequence[str]) -> RiskLevel:
    output_flags = {"-o", "-O", "--output", "--remote-name", "--output-document"}
    for index, part in enumerate(argv[1:]):
        if part in output_flags:
            return RiskLevel.LOW_WRITE
        if executable == "curl" and part.startswith("-o") and part != "-o":
            return RiskLevel.LOW_WRITE
        if executable == "wget" and part.startswith("-O") and part != "-O":
            return RiskLevel.LOW_WRITE
        if part.startswith("--output="):
            return RiskLevel.LOW_WRITE
        if part.startswith("--output-document="):
            return RiskLevel.LOW_WRITE
        if part in {"-c", "--continue"} and index > 0:
            return RiskLevel.LOW_WRITE
    return RiskLevel.READ_ONLY


def _classify_env(args: Sequence[str]) -> RiskLevel:
    for index, arg in enumerate(args):
        if arg.startswith("-"):
            continue
        if "=" in arg:
            continue
        return classify_command(args[index:])
    return RiskLevel.READ_ONLY


def _classify_python(args: Sequence[str]) -> RiskLevel:
    if any(arg in {"-c", "--command"} for arg in args):
        return RiskLevel.DANGER
    return RiskLevel.HIGH_WRITE


def _classify_shell_executor(args: Sequence[str]) -> RiskLevel:
    if args[:1] == ["--version"]:
        return RiskLevel.READ_ONLY
    return RiskLevel.DANGER


def _classify_flatpak(args: Sequence[str]) -> RiskLevel:
    if not args or args[0] in {"--version", "info", "list", "remote-info", "remote-ls"}:
        return RiskLevel.READ_ONLY
    # Every other flatpak subcommand (override, permission changes, install,
    # repair, uninstall, update, and any unknown verb) mutates the system and
    # must classify as high_write; never escalate to danger here.
    return RiskLevel.HIGH_WRITE


def _classify_git(args: Sequence[str]) -> RiskLevel:
    if not args:
        return RiskLevel.READ_ONLY

    read_only = {
        "branch",
        "diff",
        "log",
        "ls-files",
        "remote",
        "rev-parse",
        "show",
        "status",
    }
    low_write = {"clone", "fetch", "init", "ls-remote"}
    danger = {"clean", "gc", "reset"}

    command = args[0]
    if command in danger:
        return RiskLevel.DANGER
    if command in read_only:
        return RiskLevel.READ_ONLY
    if command in low_write:
        return RiskLevel.LOW_WRITE
    return RiskLevel.HIGH_WRITE


def _classify_ai_cli(executable: str, args: Sequence[str]) -> RiskLevel:
    if args[:1] in (["--version"], ["-v"]):
        return RiskLevel.READ_ONLY
    if executable == "codex" and args[:2] == ["login", "status"]:
        return RiskLevel.READ_ONLY
    return RiskLevel.HIGH_WRITE


def _basename(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").split("/")[-1]


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip().lower()
