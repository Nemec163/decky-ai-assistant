"""Internal validation and coercion helpers shared across the knowledge package.

This module holds the ``KnowledgeValidationError`` exception plus the knowledge
package's private validators. The generic validators come from the top-level
``deck_assistant_core._validation`` module and are bound here to
``KnowledgeValidationError`` so every knowledge module raises the same error type.

This module imports nothing from the other knowledge submodules, so it can be a
dependency of all of them without creating an import cycle.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from enum import Enum
from typing import Any, TypeVar

from deck_assistant_core import _validation


class KnowledgeValidationError(ValueError):
    """Raised when a knowledge contract is incomplete or inconsistent."""


_EnumT = TypeVar("_EnumT", bound=Enum)


def _require_text(value: Any, field: str) -> str:
    return _validation.require_text(value, field, error=KnowledgeValidationError)


def _optional_text(value: Any, field: str) -> None:
    if value is None:
        return
    _require_text(value, field)


def _require_bool(value: Any, field: str) -> bool:
    return _validation.require_bool(value, field, error=KnowledgeValidationError)


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    return _validation.require_mapping(value, field, error=KnowledgeValidationError)


def _require_instance(value: Any, expected_type: type[Any], field: str) -> None:
    if not isinstance(value, expected_type):
        raise KnowledgeValidationError(f"{field} must be {expected_type.__name__}")


def _validate_non_negative_int(value: Any, field: str) -> None:
    _validation.require_non_negative_int(value, field, error=KnowledgeValidationError)


def _validate_positive_int(value: Any, field: str) -> None:
    _validation.require_positive_int(value, field, error=KnowledgeValidationError)


def _validate_timestamp(value: Any, field: str) -> None:
    # Knowledge timestamps accept a trailing ``Z`` (Zulu) suffix.
    _validation.validate_timestamp(
        value,
        field,
        error=KnowledgeValidationError,
        allow_zulu=True,
    )


def _coerce_enum(value: Any, enum_type: type[_EnumT], message: str) -> _EnumT:
    return _validation.coerce_enum(
        value,
        enum_type,
        error=KnowledgeValidationError,
        message=message,
    )


def _validate_line_range(start_line: Any, end_line: Any) -> None:
    if not isinstance(start_line, int) or isinstance(start_line, bool):
        raise KnowledgeValidationError("start_line must be an integer")
    if not isinstance(end_line, int) or isinstance(end_line, bool):
        raise KnowledgeValidationError("end_line must be an integer")
    if start_line <= 0:
        raise KnowledgeValidationError("start_line must be positive")
    if end_line < start_line:
        raise KnowledgeValidationError("end_line must be greater than or equal to start_line")


def _headings(value: Sequence[Any], field: str) -> tuple[str, ...]:
    return tuple(_require_text(item, f"{field} item") for item in _sequence(value, field))


def _unique_ids(values: Iterable[str], field: str) -> set[str]:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise KnowledgeValidationError(f"duplicate {field}: {value}")
        seen.add(value)
    return seen


def _sequence(value: Any, field: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise KnowledgeValidationError(f"{field} must be a sequence")
    return value


def _get(data: Mapping[str, Any], key: str, owner: str) -> Any:
    try:
        return data[key]
    except KeyError as exc:
        raise KnowledgeValidationError(f"{owner} missing required field: {key}") from exc


def _path_value_entries(
    entries: Mapping[str, Any] | Iterable[tuple[str, Any]],
    *,
    container_error: str,
    pair_error: str,
    path_field: str,
    value_validator: Callable[[Any, str], None] | None = None,
) -> tuple[tuple[str, Any], ...]:
    """Normalize a mapping or iterable of path/value pairs into validated tuples.

    Both the manifest content map and the source-size inventory share this shape;
    ``value_validator`` lets the size variant enforce a non-negative integer while
    the content variant defers value checks to its own caller.
    """

    if isinstance(entries, Mapping):
        raw_entries: tuple[Any, ...] = tuple(entries.items())
    elif isinstance(entries, Iterable) and not isinstance(entries, (str, bytes)):
        raw_entries = tuple(entries)
    else:
        raise KnowledgeValidationError(container_error)

    normalized: list[tuple[str, Any]] = []
    for entry in raw_entries:
        if (
            isinstance(entry, (str, bytes))
            or not isinstance(entry, Sequence)
            or len(entry) != 2
        ):
            raise KnowledgeValidationError(pair_error)
        path = _require_text(entry[0], path_field)
        value = entry[1]
        if value_validator is not None:
            value_validator(value, path)
        normalized.append((path, value))
    return tuple(normalized)
