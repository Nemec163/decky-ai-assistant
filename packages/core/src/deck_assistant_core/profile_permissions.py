"""Per-profile CLI permission-bypass settings (pure, default-off).

This module is the tested core home for the explicit owner-enabled permission
bypass. The bypass is a ``danger``-level capability, so the rules here are
deliberately conservative:

- It is **off by default**: any missing, non-dict, or malformed input parses to
  an empty mapping (no profile gets a bypass).
- Only entries whose ``bypass_permissions`` flag is truthy are kept.
- Profile names are normalized through the canonical normalizer so lookups and
  persisted keys cannot drift apart.

All functions are side-effect free: no file IO, no environment access, no
logging. Callers (e.g. the Decky backend in ``main.py``) own persistence and
wire these helpers to disk.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

_PROFILE_NAME_PATTERN = re.compile(r"[^a-z0-9._-]+")

_BYPASS_KEY = "bypass_permissions"


def normalize_profile_name(value: str) -> str:
    """Return the canonical profile name.

    Lowercase the input, collapse any run of characters outside
    ``[a-z0-9._-]`` into a single ``-``, then strip leading/trailing ``.-_``.

    Raises:
        ValueError: if the normalized result is empty.
    """

    normalized = _PROFILE_NAME_PATTERN.sub("-", value.strip().lower()).strip(".-_")
    if not normalized:
        raise ValueError("profile name must not be empty")
    return normalized


def parse_profile_permissions(raw: object) -> dict[str, dict[str, bool]]:
    """Parse stored permission settings into a normalized, default-off mapping.

    Returns ``{}`` for any non-dict or malformed input. Only entries whose
    ``bypass_permissions`` value is truthy are kept; each surviving entry is
    keyed by its normalized profile name and mapped to
    ``{"bypass_permissions": True}``. Entries with empty/invalid names or
    non-dict values are ignored rather than raising.
    """

    if not isinstance(raw, Mapping):
        return {}

    permissions: dict[str, dict[str, bool]] = {}
    for raw_name, raw_config in raw.items():
        if not isinstance(raw_config, Mapping):
            continue
        if not raw_config.get(_BYPASS_KEY):
            continue
        try:
            name = normalize_profile_name(str(raw_name))
        except ValueError:
            continue
        permissions[name] = {_BYPASS_KEY: True}
    return permissions


def serialize_profile_permissions(
    permissions: Mapping[str, object],
) -> dict[str, dict[str, bool]]:
    """Serialize enabled permissions to a deterministic, normalized mapping.

    Inverse of :func:`parse_profile_permissions`. Only entries whose
    ``bypass_permissions`` value is truthy are emitted, keyed by normalized
    name, and the result is ordered by sorted key for stable, diff-friendly
    output. Invalid names or non-dict values are skipped.
    """

    enabled: dict[str, dict[str, bool]] = {}
    for raw_name, raw_config in permissions.items():
        if not isinstance(raw_config, Mapping):
            continue
        if not raw_config.get(_BYPASS_KEY):
            continue
        try:
            name = normalize_profile_name(str(raw_name))
        except ValueError:
            continue
        enabled[name] = {_BYPASS_KEY: True}
    return {name: enabled[name] for name in sorted(enabled)}


def is_bypass_enabled(permissions: Mapping[str, object], name: str) -> bool:
    """Return whether ``name`` has the permission bypass enabled.

    Performs a normalized lookup and defaults to ``False`` when the profile is
    absent, the name cannot be normalized, or the stored entry is not truthy.
    """

    try:
        normalized = normalize_profile_name(name)
    except ValueError:
        return False

    config = permissions.get(normalized)
    if not isinstance(config, Mapping):
        return False
    return bool(config.get(_BYPASS_KEY))
