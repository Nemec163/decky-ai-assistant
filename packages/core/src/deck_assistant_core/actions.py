"""Staged action contracts.

The contracts in this module describe actions for review and approval. They do
not execute commands or mutate files.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import re
from secrets import token_urlsafe
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import uuid4

from deck_assistant_core.risk import (
    ApprovalRequirement,
    RiskLevel,
    classify_command,
    classify_file_edit,
    max_risk,
)


class ActionValidationError(ValueError):
    """Raised when a staged action is not approval-ready."""


class StagedActionStoreError(RuntimeError):
    """Raised when staged action store state cannot satisfy a request."""


class StagedActionNotFound(StagedActionStoreError):
    """Raised when a staged action or approval token is unknown."""


class ApprovalRiskMismatch(StagedActionStoreError):
    """Raised when a staged action or approval token is used with the wrong expected risk."""


_REDACTED_VALUE = "[REDACTED]"
_REDACTED_PATH = "[REDACTED_PATH]"

# One canonical secret-keyword vocabulary. Every redaction structure below is
# derived from it so the keyword set cannot drift across the flag matcher, inline
# assignment matcher, secret-text matcher, and the free-text regex. Stems use the
# underscore separator; hyphen/space variants are derived where each matcher needs
# them. Adding a stem here tightens every matcher at once and never leaks more.
_SECRET_KEYWORD_STEMS = (
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "bearer",
    "client_secret",
    "cookie",
    "oauth_token",
    "passwd",
    "password",
    "refresh_token",
    "secret",
    "session_token",
    "token",
)


def _keyword_separator_variants(stem: str) -> frozenset[str]:
    """Return the underscore and hyphen spellings of a keyword stem."""

    return frozenset({stem, stem.replace("_", "-")})


# CLI flags: ``--<keyword>`` (hyphenated) plus fixed flags that carry
# credentials in practice. Short options are case-sensitive, so ``-H`` is kept
# separate from lower-case ``-h`` help flags.
_CASE_SENSITIVE_SENSITIVE_FLAGS = frozenset({"-H", "-u", "-p"})
_LOWER_SENSITIVE_FLAG_NAMES = frozenset({"--header", "--user"}) | frozenset(
    f"--{stem.replace('_', '-')}" for stem in _SECRET_KEYWORD_STEMS
)

# Inline assignment keys matched exactly after normalizing spaces to underscores;
# both hyphen and underscore spellings are accepted because the normalizer keeps
# hyphens intact.
_SENSITIVE_INLINE_KEYS = frozenset(
    variant
    for stem in _SECRET_KEYWORD_STEMS
    for variant in _keyword_separator_variants(stem)
)

# Substring markers for ``KEY=value`` assignments where KEY merely contains a
# keyword (for example ``OPENAI_API_KEY``). Underscore form is sufficient because
# the assignment key is normalized to underscores before matching.
_SENSITIVE_ASSIGNMENT_MARKERS = frozenset(_SECRET_KEYWORD_STEMS)

# ``KEY=`` / ``KEY:`` prefixes used to redact bare argv tokens, derived in both
# hyphen and underscore spellings for every stem.
_SENSITIVE_TEXT_ASSIGNMENT_PREFIXES = tuple(
    sorted(
        f"{variant}="
        for stem in _SECRET_KEYWORD_STEMS
        for variant in _keyword_separator_variants(stem)
    )
)

_SENSITIVE_PATH_SEGMENTS = frozenset(
    {
        ".aws",
        ".codex",
        ".gemini",
        ".gnupg",
        ".netrc",
        ".ssh",
        "credentials",
        "credentials.json",
        "secrets",
        "token",
        "tokens",
        "tokens.json",
    }
)


def _keyword_regex_alternative(stem: str) -> str:
    """Build a regex fragment for one stem allowing ``-``, ``_``, or space joins."""

    return re.escape(stem).replace("_", "[-_ ]?")


_SENSITIVE_TEXT_PATTERNS = (
    re.compile(
        r"(?i)\b("
        + "|".join(_keyword_regex_alternative(stem) for stem in _SECRET_KEYWORD_STEMS)
        + r")\s*([=:])\s*(\S+)"
    ),
    re.compile(r"(?i)\b(authorization\s+bearer)\s+\S+"),
    re.compile(r"(?i)\b(bearer)\s+\S+"),
)


@dataclass(frozen=True)
class CommandSpec:
    """A command represented as argv, never as an opaque shell string."""

    argv: tuple[str, ...]
    cwd: str | None = None

    @classmethod
    def from_sequence(cls, argv: Sequence[str], *, cwd: str | None = None) -> "CommandSpec":
        if isinstance(argv, str):
            raise ActionValidationError("command argv must be a sequence, not a shell string")
        if not argv:
            raise ActionValidationError("command argv must not be empty")
        return cls(argv=tuple(str(part) for part in argv), cwd=cwd)

    @property
    def risk(self) -> RiskLevel:
        return classify_command(self.argv)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"argv": list(self.argv)}
        if self.cwd is not None:
            data["cwd"] = self.cwd
        return data

    def to_approval_dict(self) -> dict[str, Any]:
        # ``_redact_argv`` already redacts URL credentials per element, so each argv
        # element is scanned exactly once here.
        rendered_argv = list(_redact_argv(self.argv))
        data: dict[str, Any] = {
            "argv": rendered_argv,
            "risk": self.risk.value,
            "has_redactions": tuple(rendered_argv) != self.argv,
        }
        if self.cwd is not None:
            data["cwd"] = _redact_path(self.cwd)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CommandSpec":
        return cls.from_sequence(data["argv"], cwd=data.get("cwd"))


@dataclass(frozen=True)
class FileEditSpec:
    """A proposed file edit for approval rendering."""

    path: str
    operation: str
    diff: str | None = None
    temporary: bool = False

    @property
    def risk(self) -> RiskLevel:
        return classify_file_edit(self.path, self.operation, temporary=self.temporary)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "path": self.path,
            "operation": self.operation,
            "temporary": self.temporary,
        }
        if self.diff is not None:
            data["diff"] = self.diff
        return data

    def to_approval_dict(self) -> dict[str, Any]:
        diff_line_count = len(self.diff.splitlines()) if self.diff is not None else 0
        return {
            "path": _redact_path(self.path),
            "operation": self.operation,
            "temporary": self.temporary,
            "risk": self.risk.value,
            "has_diff": self.diff is not None,
            "diff_line_count": diff_line_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FileEditSpec":
        return cls(
            path=str(data["path"]),
            operation=str(data["operation"]),
            diff=data.get("diff"),
            temporary=bool(data.get("temporary", False)),
        )


@dataclass(frozen=True)
class BackupSpec:
    """A backup that should exist before a write action executes."""

    source_path: str
    backup_path: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "backup_path": self.backup_path,
            "reason": self.reason,
        }

    def to_approval_dict(self) -> dict[str, Any]:
        return {
            "source_path": _redact_path(self.source_path),
            "backup_path": _redact_path(self.backup_path),
            "reason": _redact_free_text(self.reason),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BackupSpec":
        return cls(
            source_path=str(data["source_path"]),
            backup_path=str(data["backup_path"]),
            reason=str(data["reason"]),
        )


@dataclass(frozen=True)
class RollbackStep:
    """A human-reviewable rollback or restore step."""

    description: str
    command: CommandSpec | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"description": self.description}
        if self.command is not None:
            data["command"] = self.command.to_dict()
        return data

    def to_approval_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"description": _redact_free_text(self.description)}
        if self.command is not None:
            data["command"] = self.command.to_approval_dict()
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RollbackStep":
        command_data = data.get("command")
        return cls(
            description=str(data["description"]),
            command=CommandSpec.from_dict(command_data) if command_data else None,
        )


@dataclass(frozen=True)
class StagedAction:
    """Approval-ready local action description."""

    title: str
    commands: tuple[CommandSpec, ...] = ()
    file_edits: tuple[FileEditSpec, ...] = ()
    backups: tuple[BackupSpec, ...] = ()
    rollback: tuple[RollbackStep, ...] = ()
    id: str = field(default_factory=lambda: str(uuid4()))
    risk: RiskLevel | None = None
    backup_note: str | None = None
    rollback_note: str | None = None
    approved_by_user_at: str | None = None

    def __post_init__(self) -> None:
        computed = self.computed_risk
        if self.risk is None:
            object.__setattr__(self, "risk", computed)
        elif _risk_rank(self.risk) < _risk_rank(computed):
            raise ActionValidationError(
                f"declared risk {self.risk.value} is lower than computed risk {computed.value}"
            )

    @classmethod
    def create(
        cls,
        *,
        title: str,
        commands: Sequence[CommandSpec] = (),
        file_edits: Sequence[FileEditSpec] = (),
        backups: Sequence[BackupSpec] = (),
        rollback: Sequence[RollbackStep] = (),
        risk: RiskLevel | None = None,
        backup_note: str | None = None,
        rollback_note: str | None = None,
    ) -> "StagedAction":
        return cls(
            title=title,
            commands=tuple(commands),
            file_edits=tuple(file_edits),
            backups=tuple(backups),
            rollback=tuple(rollback),
            risk=risk,
            backup_note=backup_note,
            rollback_note=rollback_note,
        )

    @property
    def computed_risk(self) -> RiskLevel:
        return max_risk(
            *(command.risk for command in self.commands),
            *(file_edit.risk for file_edit in self.file_edits),
        )

    @property
    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.for_risk(self.risk or self.computed_risk)

    def validate_for_approval(self) -> None:
        if not self.title.strip():
            raise ActionValidationError("staged action title must not be empty")
        if not self.commands and not self.file_edits:
            raise ActionValidationError("staged action must include a command or file edit")

        requirement = self.approval_requirement
        # ``requirement.risk`` is always a concrete RiskLevel (derived from
        # ``self.risk or self.computed_risk``); ``self.risk`` may still be None here,
        # so use the requirement's risk for user-facing messages.
        risk_value = requirement.risk.value
        if requirement.requires_exact_commands_or_diffs:
            for file_edit in self.file_edits:
                if file_edit.operation.lower() in {
                    "append",
                    "create",
                    "delete",
                    "modify",
                    "remove",
                    "unlink",
                    "write",
                }:
                    if not file_edit.diff:
                        raise ActionValidationError(
                            "file edit for "
                            f"{file_edit.path} needs an exact diff for {risk_value}"
                        )

        if requirement.requires_backup_or_note and not self.backups and not self.backup_note:
            raise ActionValidationError(f"{risk_value} action needs backups or a backup note")

        if (
            requirement.requires_separate_confirmation
            and not self.rollback
            and not self.rollback_note
        ):
            raise ActionValidationError("danger action needs rollback steps or a rollback note")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "risk": (self.risk or self.computed_risk).value,
            "commands": [command.to_dict() for command in self.commands],
            "file_edits": [file_edit.to_dict() for file_edit in self.file_edits],
            "backups": [backup.to_dict() for backup in self.backups],
            "backup_note": self.backup_note,
            "rollback": [step.to_dict() for step in self.rollback],
            "rollback_note": self.rollback_note,
            "approved_by_user_at": self.approved_by_user_at,
        }

    def render_approval_plan(self) -> dict[str, Any]:
        """Render a deterministic, non-executable approval plan for UI/MCP clients."""

        self.validate_for_approval()
        risk = self.risk or self.computed_risk
        requirement = self.approval_requirement
        return {
            "action_id": self.id,
            "title": self.title,
            "risk": risk.value,
            "approval_gate": _render_approval_gate(requirement),
            "commands": [command.to_approval_dict() for command in self.commands],
            "file_edits": [file_edit.to_approval_dict() for file_edit in self.file_edits],
            "backups": [backup.to_approval_dict() for backup in self.backups],
            "backup_note": _redact_free_text(self.backup_note),
            "rollback": [step.to_approval_dict() for step in self.rollback],
            "rollback_note": _redact_free_text(self.rollback_note),
            "approved_by_user_at": self.approved_by_user_at,
            "summary": {
                "command_count": len(self.commands),
                "file_edit_count": len(self.file_edits),
                "backup_count": len(self.backups),
                "rollback_step_count": len(self.rollback),
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StagedAction":
        return cls(
            id=str(data["id"]),
            title=str(data["title"]),
            risk=RiskLevel(str(data["risk"])),
            commands=tuple(CommandSpec.from_dict(item) for item in data.get("commands", [])),
            file_edits=tuple(FileEditSpec.from_dict(item) for item in data.get("file_edits", [])),
            backups=tuple(BackupSpec.from_dict(item) for item in data.get("backups", [])),
            backup_note=data.get("backup_note"),
            rollback=tuple(RollbackStep.from_dict(item) for item in data.get("rollback", [])),
            rollback_note=data.get("rollback_note"),
            approved_by_user_at=data.get("approved_by_user_at"),
        )


def _risk_rank(risk: RiskLevel) -> int:
    return {
        RiskLevel.READ_ONLY: 0,
        RiskLevel.LOW_WRITE: 1,
        RiskLevel.HIGH_WRITE: 2,
        RiskLevel.DANGER: 3,
    }[risk]


def _render_approval_gate(requirement: ApprovalRequirement) -> dict[str, Any]:
    return {
        "type": _approval_gate_type(requirement),
        "summary": _approval_gate_summary(requirement),
        "requires_plan": requirement.requires_plan,
        "requires_exact_commands_or_diffs": requirement.requires_exact_commands_or_diffs,
        "requires_backup_or_note": requirement.requires_backup_or_note,
        "requires_separate_confirmation": requirement.requires_separate_confirmation,
        "may_execute_after_user_request": requirement.may_execute_after_user_request,
    }


def _approval_gate_type(requirement: ApprovalRequirement) -> str:
    if requirement.requires_separate_confirmation:
        return "separate_confirmation_required"
    if requirement.may_execute_after_user_request:
        return "user_request"
    return "approval_required"


def _approval_gate_summary(requirement: ApprovalRequirement) -> str:
    if requirement.risk is RiskLevel.READ_ONLY:
        return "User request is sufficient; no separate approval gate is required."
    if requirement.risk is RiskLevel.LOW_WRITE:
        return "Show the staged plan and wait for user approval before execution."
    if requirement.risk is RiskLevel.HIGH_WRITE:
        return "Show exact commands or diffs, plus backup context, before execution."
    return (
        "Show exact commands or diffs, backup context, and rollback details; "
        "require separate explicit confirmation before execution."
    )


def _redact_argv(argv: Sequence[str]) -> tuple[str, ...]:
    redacted: list[str] = []
    redact_next = False

    for part in argv:
        if redact_next:
            redacted.append(_REDACTED_VALUE)
            redact_next = False
            continue

        option_name = part.split("=", 1)[0]
        normalized_option = option_name.lower()
        if (
            option_name in _CASE_SENSITIVE_SENSITIVE_FLAGS
            or normalized_option in _LOWER_SENSITIVE_FLAG_NAMES
        ):
            redacted.append(part)
            redact_next = "=" not in part
            if "=" in part:
                key, _ = part.split("=", 1)
                redacted[-1] = f"{key}={_REDACTED_VALUE}"
            continue

        if _is_sensitive_assignment(part):
            key, _ = part.split("=", 1)
            redacted.append(f"{key}={_REDACTED_VALUE}")
            continue

        if _looks_like_url_with_credentials(part):
            redacted.append(_redact_argv_part(part))
            continue

        if _looks_like_secret_text(part):
            redacted.append(_REDACTED_VALUE)
            continue

        redacted.append(part)

    return tuple(redacted)


def _is_sensitive_assignment(value: str) -> bool:
    if "=" not in value:
        return False
    key, _ = value.split("=", 1)
    normalized = key.strip().lower().replace(" ", "_")
    return normalized in _SENSITIVE_INLINE_KEYS or any(
        marker in normalized for marker in _SENSITIVE_ASSIGNMENT_MARKERS
    )


def _looks_like_secret_text(value: str) -> bool:
    lowered = value.lower()
    return (
        lowered.startswith("authorization:")
        or lowered.startswith("authorization=")
        or lowered.startswith("bearer ")
        or any(prefix in lowered for prefix in _SENSITIVE_TEXT_ASSIGNMENT_PREFIXES)
    )


def _looks_like_url_with_credentials(value: str) -> bool:
    if "://" not in value or "@" not in value:
        return False
    scheme, rest = value.split("://", 1)
    if not scheme:
        return False
    return ":" in rest.split("@", 1)[0]


def _redact_argv_part(value: str) -> str:
    if _looks_like_url_with_credentials(value):
        scheme, rest = value.split("://", 1)
        _, suffix = rest.split("@", 1)
        return f"{scheme}://{_REDACTED_VALUE}@{suffix}"
    return value


def _redact_path(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace("\\", "/").lower()
    segments = [segment for segment in normalized.split("/") if segment]
    if any(segment in _SENSITIVE_PATH_SEGMENTS for segment in segments):
        return _REDACTED_PATH
    if "/.config/codex/" in normalized or normalized.endswith("/.config/codex"):
        return _REDACTED_PATH
    return value


def _redact_free_text(value: str | None) -> str | None:
    if value is None:
        return None

    redacted = value
    if _looks_like_url_with_credentials(redacted):
        redacted = _redact_argv_part(redacted)

    for pattern in _SENSITIVE_TEXT_PATTERNS:
        redacted = pattern.sub(_replace_sensitive_text, redacted)
    return redacted


def _replace_sensitive_text(match: re.Match[str]) -> str:
    if match.lastindex is not None and match.lastindex >= 2:
        return f"{match.group(1)}{match.group(2)} {_REDACTED_VALUE}"
    return f"{match.group(1)} {_REDACTED_VALUE}"


@dataclass(frozen=True)
class StagedActionMetadata:
    """Public staging metadata that does not expose execution credentials."""

    action_id: str
    risk: RiskLevel
    staged_at: str
    approved_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "risk": self.risk.value,
            "staged_at": self.staged_at,
            "approved_at": self.approved_at,
        }


@dataclass(frozen=True)
class ApprovalTokenMetadata:
    """Opaque token metadata issued only after Decky approval."""

    token: str
    action_id: str
    risk: RiskLevel
    issued_at: str
    approved_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "action_id": self.action_id,
            "risk": self.risk.value,
            "issued_at": self.issued_at,
            "approved_at": self.approved_at,
        }


TokenFactory = Callable[[], str]
TimestampFactory = Callable[[], str]


class StagedActionStore:
    """Approval-aware in-memory store for staged actions.

    The store only validates, records, retrieves, and marks action approval. It
    never executes commands and never mutates files.
    """

    def __init__(
        self,
        *,
        token_factory: TokenFactory | None = None,
        timestamp_factory: TimestampFactory | None = None,
    ) -> None:
        self._token_factory = token_factory or (lambda: token_urlsafe(32))
        self._timestamp_factory = timestamp_factory or _utc_timestamp
        self._actions: dict[str, StagedAction] = {}
        self._staged: dict[str, StagedActionMetadata] = {}
        self._tokens: dict[str, ApprovalTokenMetadata] = {}
        self._lock = RLock()

    def stage_action(self, action: StagedAction) -> StagedActionMetadata:
        """Validate and stage an action without releasing an approval token."""

        action.validate_for_approval()
        risk = action.risk or action.computed_risk

        with self._lock:
            if action.id in self._actions:
                raise ActionValidationError(f"staged action id already exists: {action.id}")

            metadata = StagedActionMetadata(
                action_id=action.id,
                risk=risk,
                staged_at=self._timestamp_factory(),
            )
            self._actions[action.id] = action
            self._staged[action.id] = metadata
            return metadata

    def get_staged_action(
        self,
        staged_action_id: str,
        *,
        expected_risk: RiskLevel | str,
    ) -> StagedAction:
        """Return a staged action by id only when the caller's expected risk matches."""

        expected = _coerce_risk(expected_risk)
        with self._lock:
            metadata = self._require_staged_metadata(staged_action_id)
            self._require_matching_risk(metadata, expected)
            return self._require_action(metadata)

    def mark_approved(
        self,
        staged_action_id: str,
        *,
        expected_risk: RiskLevel | str,
        approved_at: str | None = None,
    ) -> ApprovalTokenMetadata:
        """Mark a staged action approved and issue its opaque Decky approval token."""

        expected = _coerce_risk(expected_risk)
        timestamp = approved_at or self._timestamp_factory()
        if not timestamp.strip():
            raise ActionValidationError("approval timestamp must not be empty")

        with self._lock:
            staged = self._require_staged_metadata(staged_action_id)
            if staged.approved_at is not None:
                raise ActionValidationError(f"staged action is already approved: {staged_action_id}")
            self._require_matching_risk(staged, expected)
            action = self._require_action(staged)
            token = self._new_token()
            token_metadata = ApprovalTokenMetadata(
                token=token,
                action_id=action.id,
                risk=expected,
                issued_at=timestamp,
                approved_at=timestamp,
            )
            approved_action = replace(action, approved_by_user_at=timestamp)
            self._actions[action.id] = approved_action
            self._staged[action.id] = replace(staged, approved_at=timestamp)
            self._tokens[token] = token_metadata
            return token_metadata

    def get_approved_action(
        self,
        staged_action_id: str,
        approval_token: str,
        *,
        expected_risk: RiskLevel | str,
    ) -> StagedAction:
        """Return an approved action only for the matching action id, token, and risk."""

        expected = _coerce_risk(expected_risk)
        with self._lock:
            staged = self._require_staged_metadata(staged_action_id)
            self._require_matching_risk(staged, expected)
            metadata = self._require_token_metadata(approval_token)
            self._require_matching_risk(metadata, expected)
            if metadata.action_id != staged_action_id:
                raise StagedActionNotFound("approval token does not match staged action")
            action = self._require_action(staged)
            if action.approved_by_user_at is None:
                raise StagedActionNotFound("staged action is not approved")
            return action

    def get_token_metadata(self, approval_token: str) -> ApprovalTokenMetadata:
        """Return approval token metadata without exposing action execution paths."""

        with self._lock:
            return self._require_token_metadata(approval_token)

    def get_staged_metadata(self, staged_action_id: str) -> StagedActionMetadata:
        """Return non-secret staged action metadata by staged action id."""

        with self._lock:
            return self._require_staged_metadata(staged_action_id)

    def _new_token(self) -> str:
        token = self._token_factory()
        if not token.strip():
            raise StagedActionStoreError("approval token must not be empty")
        if token in self._tokens:
            raise StagedActionStoreError("approval token already exists")
        return token

    def _require_token_metadata(self, approval_token: str) -> ApprovalTokenMetadata:
        try:
            return self._tokens[approval_token]
        except KeyError as exc:
            raise StagedActionNotFound("approval token is not approved") from exc

    def _require_staged_metadata(self, staged_action_id: str) -> StagedActionMetadata:
        try:
            return self._staged[staged_action_id]
        except KeyError as exc:
            raise StagedActionNotFound("staged action is not staged") from exc

    def _require_action(self, metadata: StagedActionMetadata | ApprovalTokenMetadata) -> StagedAction:
        try:
            return self._actions[metadata.action_id]
        except KeyError as exc:
            raise StagedActionNotFound(
                f"staged action is missing: {metadata.action_id}"
            ) from exc

    @staticmethod
    def _require_matching_risk(
        metadata: StagedActionMetadata | ApprovalTokenMetadata,
        expected_risk: RiskLevel,
    ) -> None:
        if metadata.risk is not expected_risk:
            raise ApprovalRiskMismatch(
                "approval token risk mismatch: "
                f"expected {expected_risk.value}, got {metadata.risk.value}"
            )


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_risk(risk: RiskLevel | str) -> RiskLevel:
    if isinstance(risk, RiskLevel):
        return risk
    return RiskLevel(str(risk))
