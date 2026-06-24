"""PTY session manager for Terminal Mode.

This module owns process lifecycle only. It starts known CLI profiles through a
real PTY, streams bytes, resizes the terminal, and stops child processes. It
does not inspect AI CLI credential stores or execute opaque shell strings.
"""

from __future__ import annotations

import errno
import os
import select
import signal
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from deck_assistant_core.cli import (
    CliProfile,
    WhichFunc,
    apply_managed_user_identity,
    get_cli_profile,
    managed_cli_cache_home,
    managed_cli_bin_dirs,
    managed_cli_config_home,
    managed_cli_data_dir,
    managed_cli_profile_workspace_dir,
    managed_cli_user_home,
    resolve_executable,
)

if os.name == "posix":
    import fcntl
    import pty
    import struct
    import termios
else:
    fcntl = None  # type: ignore[assignment]
    pty = None  # type: ignore[assignment]
    struct = None  # type: ignore[assignment]
    termios = None  # type: ignore[assignment]


class PtySessionError(RuntimeError):
    """Raised when a PTY session cannot be created or controlled."""


class PtySessionNotFound(PtySessionError):
    """Raised when a session id is unknown."""


_CHILD_ENV_PATH_HINTS = (
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/home/deck/.local/bin",
    "/home/deck/bin",
)

# Grace period granted to a SIGKILL'd process group before giving up the poll
# loop. SIGKILL cannot be caught, so this only needs to cover reaping latency.
_SIGKILL_GRACE_SECONDS = 0.2

# Sleep between process-exit polls while waiting out a termination grace window.
_STOP_POLL_INTERVAL_SECONDS = 0.02

_UNSAFE_CHILD_ENV_KEYS = (
    # Decky Loader and Steam runtime can expose compatibility libraries that
    # break system shells, e.g. bash/readline symbol lookup failures.
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "LD_AUDIT",
    "LD_ORIGIN_PATH",
    # macOS equivalents keep local development smoke tests isolated.
    "DYLD_LIBRARY_PATH",
    "DYLD_FALLBACK_LIBRARY_PATH",
    "DYLD_INSERT_LIBRARIES",
)


@dataclass(frozen=True)
class PtySessionSnapshot:
    """Serializable view of one managed PTY session."""

    id: str
    profile_name: str
    display_name: str
    pid: int
    argv: tuple[str, ...]
    cwd: str | None
    cols: int
    rows: int
    started_at: float
    running: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "profile_name": self.profile_name,
            "display_name": self.display_name,
            "pid": self.pid,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "cols": self.cols,
            "rows": self.rows,
            "started_at": self.started_at,
            "running": self.running,
        }


@dataclass(frozen=True)
class _LaunchSpec:
    profile: CliProfile
    executable_path: str
    argv: tuple[str, ...]
    cwd: str | None
    env: dict[str, str]
    cols: int
    rows: int


@dataclass
class _ManagedSession:
    id: str
    spec: _LaunchSpec
    master_fd: int
    pid: int
    started_at: float
    cols: int
    rows: int
    process_exited: bool = False
    fd_closed: bool = False


IdFactory = Callable[[], str]
Clock = Callable[[], float]


class PtySessionManager:
    """Manage bounded PTY sessions for known CLI profiles."""

    def __init__(
        self,
        *,
        which: WhichFunc | None = None,
        id_factory: IdFactory | None = None,
        clock: Clock | None = None,
        max_sessions: int = 4,
        profiles: Sequence[CliProfile] | None = None,
    ) -> None:
        if max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        self._which = which or _default_which
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._clock = clock or time.time
        self._max_sessions = max_sessions
        self._sessions: dict[str, _ManagedSession] = {}
        self._profiles: dict[str, CliProfile] = {}
        self.set_profiles(profiles or ())

    def set_profiles(self, profiles: Sequence[CliProfile]) -> None:
        """Replace custom profile definitions available to future sessions."""

        self._profiles = {}
        for profile in profiles:
            if not isinstance(profile, CliProfile):
                raise PtySessionError("PTY profiles must be CliProfile instances")
            self._profiles[profile.name.strip().lower()] = profile

    def start_session(
        self,
        profile_name: str,
        *,
        cwd: str | None = None,
        cols: int = 80,
        rows: int = 24,
    ) -> PtySessionSnapshot:
        """Start a known CLI profile in a PTY and return its session snapshot."""

        _ensure_posix()
        if len(self._sessions) >= self._max_sessions:
            raise PtySessionError("maximum PTY session count reached")
        spec = self._resolve_launch_spec(profile_name, cwd=cwd, cols=cols, rows=rows)
        session_id = self._new_session_id()
        return self._spawn_session(session_id, spec)

    def start_transient_session(
        self,
        profile: CliProfile,
        *,
        cwd: str | None = None,
        cols: int = 80,
        rows: int = 24,
    ) -> PtySessionSnapshot:
        """Start an explicit one-off profile without adding it to stored profiles."""

        _ensure_posix()
        if len(self._sessions) >= self._max_sessions:
            raise PtySessionError("maximum PTY session count reached")
        if not isinstance(profile, CliProfile):
            raise PtySessionError("transient PTY profile must be a CliProfile instance")
        spec = self._resolve_profile_launch_spec(profile, cwd=cwd, cols=cols, rows=rows)
        session_id = self._new_session_id()
        return self._spawn_session(session_id, spec)

    def open_transient_session(
        self,
        profile: CliProfile,
        *,
        cwd: str | None = None,
        cols: int = 80,
        rows: int = 24,
    ) -> PtySessionSnapshot:
        """Return a running transient profile session, or start one if none is alive."""

        _ensure_posix()
        _validate_dimensions(cols=cols, rows=rows)
        if not isinstance(profile, CliProfile):
            raise PtySessionError("transient PTY profile must be a CliProfile instance")

        return self._open_or_reuse(
            profile.name,
            cols=cols,
            rows=rows,
            start=lambda: self.start_transient_session(profile, cwd=cwd, cols=cols, rows=rows),
        )

    def open_profile_session(
        self,
        profile_name: str,
        *,
        cwd: str | None = None,
        cols: int = 80,
        rows: int = 24,
    ) -> PtySessionSnapshot:
        """Return a running profile session, or start one if none is alive."""

        _ensure_posix()
        _validate_dimensions(cols=cols, rows=rows)

        return self._open_or_reuse(
            profile_name,
            cols=cols,
            rows=rows,
            start=lambda: self.start_session(profile_name, cwd=cwd, cols=cols, rows=rows),
        )

    def _open_or_reuse(
        self,
        profile_name: str,
        *,
        cols: int,
        rows: int,
        start: Callable[[], PtySessionSnapshot],
    ) -> PtySessionSnapshot:
        """Reuse a live session for this profile, or start one via ``start``.

        Both the lookup name and the stored profile name are normalized before
        comparison so mixed-case profiles map onto the same managed session.
        """

        normalized = profile_name.strip().lower()

        for session_id in sorted(self._sessions):
            session = self._sessions[session_id]
            if self._session_profile_matches(session, normalized) and self._process_running(session):
                if session.cols != cols or session.rows != rows:
                    return self.resize_session(session.id, cols=cols, rows=rows)
                return self._snapshot(session)

        for session_id in tuple(sorted(self._sessions)):
            session = self._sessions[session_id]
            if self._session_profile_matches(session, normalized) and not self._process_running(session):
                self._stop_managed_session(session)
                self._sessions.pop(session_id, None)

        return start()

    @staticmethod
    def _session_profile_matches(session: _ManagedSession, normalized_name: str) -> bool:
        return session.spec.profile.name.strip().lower() == normalized_name

    def restart_session(self, session_id: str) -> PtySessionSnapshot:
        """Stop and restart an existing session with the same id and profile."""

        session = self._require_session(session_id)
        spec = _LaunchSpec(
            profile=session.spec.profile,
            executable_path=session.spec.executable_path,
            argv=session.spec.argv,
            cwd=session.spec.cwd,
            env=session.spec.env,
            cols=session.cols,
            rows=session.rows,
        )
        self._stop_managed_session(session)
        self._sessions.pop(session_id, None)
        return self._spawn_session(session_id, spec)

    def write_session(self, session_id: str, data: str | bytes) -> int:
        """Write bytes or UTF-8 text to a running PTY session."""

        session = self._require_session(session_id)
        if not self._process_running(session):
            raise PtySessionError(f"PTY session is not running: {session_id}")

        payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        if not payload:
            return 0

        sent = 0
        view = memoryview(payload)
        while sent < len(payload):
            try:
                written = os.write(session.master_fd, view[sent:])
            except OSError as exc:
                if exc.errno in {errno.EBADF, errno.EIO, errno.EPIPE}:
                    self._mark_fd_closed(session)
                raise PtySessionError(f"could not write to PTY session: {session_id}") from exc
            if written == 0:
                raise PtySessionError(f"could not write to PTY session: {session_id}")
            sent += written
        return sent

    def read_session(
        self,
        session_id: str,
        *,
        max_bytes: int = 65536,
        timeout_seconds: float = 0.0,
    ) -> bytes:
        """Read currently available PTY bytes without blocking past timeout."""

        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must not be negative")

        session = self._require_session(session_id)
        if session.fd_closed:
            return b""

        ready = self._select_readable(session, timeout_seconds)
        if not ready:
            self._process_running(session)
            return b""

        chunks: list[bytes] = []
        remaining = max_bytes
        while remaining > 0:
            try:
                chunk = os.read(session.master_fd, min(remaining, 4096))
            except BlockingIOError:
                break
            except OSError as exc:
                if exc.errno in {errno.EBADF, errno.EIO}:
                    self._mark_fd_closed(session)
                    break
                raise PtySessionError(f"could not read from PTY session: {session_id}") from exc

            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
            if not self._select_readable(session, 0.0):
                break

        self._process_running(session)
        return b"".join(chunks)

    def resize_session(self, session_id: str, *, cols: int, rows: int) -> PtySessionSnapshot:
        """Resize a PTY session and return the updated snapshot."""

        _validate_dimensions(cols=cols, rows=rows)
        session = self._require_session(session_id)
        if not session.fd_closed:
            _set_window_size(session.master_fd, cols=cols, rows=rows)
        session.cols = cols
        session.rows = rows
        return self._snapshot(session)

    def send_interrupt(self, session_id: str) -> int:
        """Send Ctrl+C through the PTY, matching terminal user behavior."""

        return self.write_session(session_id, b"\x03")

    def stop_session(self, session_id: str, *, terminate_grace_seconds: float = 0.5) -> None:
        """Stop one session and remove it from the manager."""

        if terminate_grace_seconds < 0:
            raise ValueError("terminate_grace_seconds must not be negative")
        session = self._require_session(session_id)
        self._stop_managed_session(session, terminate_grace_seconds=terminate_grace_seconds)
        self._sessions.pop(session_id, None)

    def stop_all_sessions(self) -> None:
        """Stop all sessions currently known to the manager."""

        for session_id in tuple(self._sessions):
            self.stop_session(session_id)

    def get_session(self, session_id: str) -> PtySessionSnapshot:
        """Return a snapshot for one session."""

        return self._snapshot(self._require_session(session_id))

    def list_sessions(self) -> tuple[PtySessionSnapshot, ...]:
        """Return snapshots for all known sessions in stable id order."""

        return tuple(self._snapshot(self._sessions[key]) for key in sorted(self._sessions))

    def _resolve_launch_spec(
        self,
        profile_name: str,
        *,
        cwd: str | None,
        cols: int,
        rows: int,
    ) -> _LaunchSpec:
        profile = self._get_profile(profile_name)
        return self._resolve_profile_launch_spec(profile, cwd=cwd, cols=cols, rows=rows)

    def _resolve_profile_launch_spec(
        self,
        profile: CliProfile,
        *,
        cwd: str | None,
        cols: int,
        rows: int,
    ) -> _LaunchSpec:
        _validate_dimensions(cols=cols, rows=rows)
        resolved_cwd = _validate_cwd(cwd) if cwd is not None else _default_cwd(profile)
        executable_path = self._which(profile.executable)
        if executable_path is None:
            raise PtySessionError(f"{profile.executable} was not found on PATH.")
        env = build_terminal_child_env(
            executable_path=executable_path,
            cols=cols,
            rows=rows,
            cwd=resolved_cwd,
            shell_path=executable_path if profile.name == "bash" else None,
        )
        return _LaunchSpec(
            profile=profile,
            executable_path=executable_path,
            argv=profile.launch_argv(executable_path),
            cwd=resolved_cwd,
            env=env,
            cols=cols,
            rows=rows,
        )

    def _get_profile(self, profile_name: str) -> CliProfile:
        normalized = profile_name.strip().lower()
        profile = self._profiles.get(normalized)
        if profile is not None:
            return profile
        return get_cli_profile(profile_name)

    def _new_session_id(self) -> str:
        session_id = self._id_factory()
        if not session_id.strip():
            raise PtySessionError("PTY session id must not be empty")
        if session_id in self._sessions:
            raise PtySessionError(f"PTY session id already exists: {session_id}")
        return session_id

    def _spawn_session(self, session_id: str, spec: _LaunchSpec) -> PtySessionSnapshot:
        if pty is None:
            raise PtySessionError("PTY sessions require POSIX pty support.")
        pid, master_fd = pty.fork()
        if pid == 0:
            try:
                child_env = dict(spec.env)
                try:
                    child_env["SSH_TTY"] = os.ttyname(0)
                except OSError:
                    pass
                if spec.cwd is not None:
                    os.chdir(spec.cwd)
                os.execve(spec.executable_path, spec.argv, child_env)
            except BaseException:
                # In the forked child, an exception must never propagate back
                # into the parent's Python state; force an immediate hard exit
                # so a failed exec cannot run duplicated interpreter code.
                os._exit(127)

        _set_nonblocking(master_fd)
        _set_window_size(master_fd, cols=spec.cols, rows=spec.rows)

        session = _ManagedSession(
            id=session_id,
            spec=spec,
            master_fd=master_fd,
            pid=pid,
            started_at=self._clock(),
            cols=spec.cols,
            rows=spec.rows,
        )
        self._sessions[session_id] = session
        return self._snapshot(session)

    def _require_session(self, session_id: str) -> _ManagedSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise PtySessionNotFound(f"unknown PTY session: {session_id}") from exc

    def _snapshot(self, session: _ManagedSession) -> PtySessionSnapshot:
        return PtySessionSnapshot(
            id=session.id,
            profile_name=session.spec.profile.name,
            display_name=session.spec.profile.display_name,
            pid=session.pid,
            argv=session.spec.argv,
            cwd=session.spec.cwd,
            cols=session.cols,
            rows=session.rows,
            started_at=session.started_at,
            running=self._process_running(session),
        )

    def _select_readable(self, session: _ManagedSession, timeout_seconds: float) -> bool:
        if session.fd_closed:
            return False
        try:
            readable, _, _ = select.select([session.master_fd], [], [], timeout_seconds)
        except OSError as exc:
            if exc.errno == errno.EBADF:
                self._mark_fd_closed(session)
                return False
            raise PtySessionError(f"could not poll PTY session: {session.id}") from exc
        return bool(readable)

    def _process_running(self, session: _ManagedSession) -> bool:
        if session.process_exited:
            return False
        try:
            waited_pid, _ = os.waitpid(session.pid, os.WNOHANG)
        except ChildProcessError:
            session.process_exited = True
            return False
        if waited_pid == 0:
            return True
        session.process_exited = True
        return False

    def _stop_managed_session(
        self,
        session: _ManagedSession,
        *,
        terminate_grace_seconds: float = 0.5,
    ) -> None:
        escalation = (
            (signal.SIGHUP, terminate_grace_seconds),
            (signal.SIGTERM, terminate_grace_seconds),
            (signal.SIGKILL, _SIGKILL_GRACE_SECONDS),
        )
        for sig, grace_seconds in escalation:
            if not self._process_running(session):
                break
            _signal_process_group(session.pid, sig)
            deadline = time.monotonic() + grace_seconds
            while time.monotonic() < deadline and self._process_running(session):
                time.sleep(_STOP_POLL_INTERVAL_SECONDS)

        self._mark_fd_closed(session)

    def _mark_fd_closed(self, session: _ManagedSession) -> None:
        if session.fd_closed:
            return
        try:
            os.close(session.master_fd)
        except OSError:
            pass
        session.fd_closed = True


def _default_which(executable: str) -> str | None:
    return resolve_executable(executable)


def build_terminal_child_env(
    *,
    executable_path: str,
    cols: int,
    rows: int,
    cwd: str | None,
    shell_path: str | None = None,
) -> dict[str, str]:
    """Build a PTY child environment that does not inherit Decky loader libs."""

    env = dict(os.environ)
    for key in _UNSAFE_CHILD_ENV_KEYS:
        env.pop(key, None)

    env["PATH"] = _merged_child_path(env.get("PATH", ""), executable_path)
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    env["LINES"] = str(rows)
    env["COLUMNS"] = str(cols)
    if cwd is not None:
        env["PWD"] = cwd
    if shell_path is not None:
        env["SHELL"] = shell_path
    env["HOME"] = managed_cli_user_home()
    env["XDG_DATA_HOME"] = os.path.dirname(managed_cli_data_dir())
    env["XDG_CONFIG_HOME"] = managed_cli_config_home()
    env["XDG_CACHE_HOME"] = managed_cli_cache_home()
    apply_managed_user_identity(env)
    if os.name == "posix":
        env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return env


def _merged_child_path(existing_path: str, executable_path: str) -> str:
    parts: list[str] = []
    executable_dir = os.path.dirname(executable_path)
    for raw_part in (
        os.pathsep.join(managed_cli_bin_dirs()),
        existing_path,
        executable_dir,
        os.pathsep.join(_CHILD_ENV_PATH_HINTS),
    ):
        for part in raw_part.split(os.pathsep):
            normalized = part.strip()
            if normalized and normalized not in parts:
                parts.append(normalized)
    return os.pathsep.join(parts)


def _default_cwd(profile: CliProfile | None = None) -> str | None:
    if profile is not None:
        workspace_profile = _managed_workspace_profile(profile)
        workspace = (
            managed_cli_profile_workspace_dir(workspace_profile)
            if workspace_profile is not None
            else None
        )
        if workspace is not None and os.path.isdir(workspace):
            return workspace

    home = managed_cli_user_home()
    if home and os.path.isdir(home):
        return home
    return None


def _managed_workspace_profile(profile: CliProfile) -> str | None:
    if profile.name == "codex" or profile.name.startswith("setup-codex-"):
        return "codex"
    if profile.name == "claude" or profile.name.startswith("setup-claude-"):
        return "claude"
    return None


def _ensure_posix() -> None:
    if os.name != "posix":
        raise PtySessionError("PTY sessions require a POSIX runtime.")


def _validate_dimensions(*, cols: int, rows: int) -> None:
    if cols < 1 or rows < 1:
        raise ValueError("PTY dimensions must be positive")
    if cols > 500 or rows > 200:
        raise ValueError("PTY dimensions are outside the supported bounds")


def _validate_cwd(cwd: str | None) -> str | None:
    if cwd is None:
        return None
    resolved = os.path.abspath(cwd)
    if not os.path.isdir(resolved):
        raise PtySessionError(f"PTY cwd does not exist or is not a directory: {cwd}")
    return resolved


def _set_nonblocking(fd: int) -> None:
    if fcntl is None:
        raise PtySessionError("PTY sessions require fcntl support.")
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def _set_window_size(fd: int, *, cols: int, rows: int) -> None:
    if fcntl is None or struct is None or termios is None:
        raise PtySessionError("PTY sessions require POSIX terminal support.")
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def _signal_process_group(pid: int, sig: signal.Signals) -> None:
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        return
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
