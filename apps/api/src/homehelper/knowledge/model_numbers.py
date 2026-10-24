"""Model-number and error-code normalization and matching (spec §10.4, M1-06). Pure functions."""

import re
from fnmatch import fnmatchcase

# Below this length a bare user-typed prefix ("WM") is too ambiguous to match a pattern.
MIN_PARTIAL_MODEL_LENGTH = 4

_NON_MODEL_CHARS = re.compile(r"[^A-Z0-9*?]")
_NON_CODE_CHARS = re.compile(r"[^A-Z0-9]")


# What people type when they don't have a model number ("not sure", "N/A", "idk").
_NOT_A_MODEL = re.compile(
    r"\b(unknown|not sure|don'?t know|no idea|idk|n/?a|none|can'?t find|cannot find)\b", re.I
)


def looks_like_model(value: str) -> bool:
    """A model number has at least three letters or digits and usually a digit; without one it
    is a single word in capitals of at least four ("BVMC-HC", "WHAPSRO"). An answer like "I
    don't know" is not one."""
    if _NOT_A_MODEL.search(value):
        return False
    compact = _NON_MODEL_CHARS.sub("", value.upper()).replace("*", "").replace("?", "")
    if any(c.isdigit() for c in compact):
        return len(compact) >= 3
    word = value.strip()
    return len(compact) >= 4 and " " not in word and word == word.upper()


def normalize_model(value: str) -> str:
    """Uppercase and drop separators (spaces, `-`, `/`, `.`); keeps `*`/`?` wildcards."""
    return _NON_MODEL_CHARS.sub("", value.upper())


def _fixed_prefix(pattern: str) -> str:
    match = re.search(r"[*?]", pattern)
    return pattern[: match.start()] if match else pattern


def model_matches(model: str, pattern: str) -> bool:
    """Does a user/vision-supplied model number belong to a manual's model pattern?

    Matches when the full model fits the glob (`WM3400CW` ~ `WM3400*`), when a wildcard-free
    pattern is a prefix of the model (`WM3400` ~ `WM3400CW`, color/region suffixes), or when the
    user typed only a leading part of the model (`WM34` ~ `WM3400*`, at least 4 characters).
    """
    model_n = normalize_model(model).replace("*", "").replace("?", "")
    pattern_n = normalize_model(pattern)
    if not model_n or not pattern_n:
        return False
    if fnmatchcase(model_n, pattern_n):
        return True
    fixed = _fixed_prefix(pattern_n)
    if fixed == pattern_n and model_n.startswith(fixed):
        return True
    return len(model_n) >= MIN_PARTIAL_MODEL_LENGTH and fixed.startswith(model_n)


def matches_any(model: str, patterns: list[str]) -> bool:
    return any(model_matches(model, pattern) for pattern in patterns)


def normalize_error_code(code: str) -> str:
    """`" o-e "` -> `"OE"`."""
    return _NON_CODE_CHARS.sub("", code.upper())


def error_code_variants(code: str) -> list[str]:
    """The normalized code plus O/0 and I/1 look-alike swaps (users type `0E` for LG's `OE`)."""
    base = normalize_error_code(code)
    if not base:
        return []
    variants = [base]
    for a, b in (("O", "0"), ("0", "O"), ("I", "1"), ("1", "I")):
        if a in base:
            swapped = base.replace(a, b)
            if swapped not in variants:
                variants.append(swapped)
    return variants
