"""Shared, exception-parameterized validators for core domain contracts.

Every validator takes an explicit ``error`` exception type so callers raise their
own module-specific validation error (``KnowledgeValidationError``,
``DiagnosticsValidationError``, ``ActionValidationError``) while sharing a single
implementation. This module imports nothing from the domain modules, so it never
introduces import cycles.

Behavior notes that callers depend on:

- ``require_text`` returns the value unchanged by default; pass ``strip=True`` to
  return ``value.strip()`` (diagnostics relies on the stripped form).
- ``validate_timestamp`` rejects a trailing ``Z`` unless ``allow_zulu=True``;
  knowledge accepts the Zulu suffix while diagnostics does not. The accepted
  formats of each module must not change.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar


_EnumT = TypeVar("_EnumT", bound=Enum)


def require_text(
    value: Any,
    field: str,
    *,
    error: type[Exception],
    strip: bool = False,
) -> str:
    """Return a non-empty string, raising ``error`` otherwise.

    When ``strip`` is ``True`` the returned value is ``value.strip()``; otherwise
    the original string is returned unchanged. Emptiness is always judged after
    stripping so whitespace-only values are rejected in both modes.
    """

    if not isinstance(value, str) or not value.strip():
        raise error(f"{field} must not be empty")
    return value.strip() if strip else value


def require_bool(value: Any, field: str, *, error: type[Exception]) -> bool:
    if not isinstance(value, bool):
        raise error(f"{field} must be a boolean")
    return value


def require_mapping(value: Any, field: str, *, error: type[Exception]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise error(f"{field} must be a mapping")
    return value


def require_non_negative_int(value: Any, field: str, *, error: type[Exception]) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise error(f"{field} must be an integer")
    if value < 0:
        raise error(f"{field} must not be negative")
    return value


def require_positive_int(value: Any, field: str, *, error: type[Exception]) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise error(f"{field} must be an integer")
    if value <= 0:
        raise error(f"{field} must be positive")
    return value


def coerce_enum(
    value: _EnumT | str,
    enum_type: type[_EnumT],
    *,
    error: type[Exception],
    message: str,
) -> _EnumT:
    """Return an enum member, accepting either a member or its string value."""

    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except ValueError as exc:
        raise error(f"{message}: {value}") from exc


def validate_timestamp(
    value: Any,
    field: str,
    *,
    error: type[Exception],
    allow_zulu: bool = False,
) -> str:
    """Validate an ISO 8601/8601-with-Zulu timestamp and return it unchanged.

    With ``allow_zulu=True`` a trailing ``Z`` is normalized to ``+00:00`` before
    parsing (knowledge semantics). With ``allow_zulu=False`` the value must be a
    bare ``datetime.fromisoformat`` string (diagnostics semantics).
    """

    if allow_zulu:
        text = require_text(value, field, error=error)
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise error(f"{field} must be an ISO 8601 timestamp") from exc
        return text

    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise error(f"{field} must be an ISO-8601 date-time string") from exc
    return value
