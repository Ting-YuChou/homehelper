import pytest

from homehelper.knowledge.model_numbers import (
    error_code_variants,
    looks_like_model,
    matches_any,
    model_matches,
    normalize_error_code,
    normalize_model,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("wm3400cw", "WM3400CW"),
        ("WM 3400-CW", "WM3400CW"),
        ("DV45K6500EW/A3", "DV45K6500EWA3"),
        ("NN-CS89.LS", "NNCS89LS"),
        ("WM6998H*A", "WM6998H*A"),
        ("", ""),
    ],
)
def test_normalize_model(raw: str, expected: str) -> None:
    assert normalize_model(raw) == expected


@pytest.mark.parametrize(
    ("model", "pattern", "expected"),
    [
        ("WM3400CW", "WM3400*", True),  # glob
        ("wm-3400 cw", "WM3400*", True),  # separators and case
        ("WM6998HBA", "WM6998H*A", True),  # wildcard in the middle (LG color code)
        ("WM6998HBB", "WM6998H*A", False),
        ("WD5100DW", "WD5100D", True),  # wildcard-free pattern is a prefix of the model
        ("WM34", "WM3400*", True),  # user typed a leading part (>= 4 chars)
        ("WM3", "WM3400*", False),  # too short to be meaningful
        ("WM3500CW", "WM3400*", False),
        ("DV45K6500EW/A3", "DV45K6500*", True),
        ("", "WM3400*", False),
        ("WM3400", "", False),
    ],
)
def test_model_matches(model: str, pattern: str, expected: bool) -> None:
    assert model_matches(model, pattern) is expected


def test_matches_any() -> None:
    assert matches_any("WD53DBA", ["WD5100D*", "WD53DB*"])
    assert not matches_any("WD53DBA", [])


def test_error_codes() -> None:
    assert normalize_error_code(" o-e ") == "OE"
    assert error_code_variants("OE") == ["OE", "0E"]
    assert error_code_variants("0e") == ["0E", "OE"]
    assert error_code_variants("4C") == ["4C"]
    assert error_code_variants("E1") == ["E1", "EI"]
    assert error_code_variants("--") == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("WM3400CW", True),
        ("rf28r7351sr", True),
        ("BVMC-HC", True),
        ("WHAPSRO", True),
        ("BEFX", True),
        ("A1", False),
        ("LG", False),
        ("front", False),
        ("Front Load", False),
        ("I don't know", False),
        ("N/A", False),
        ("UNKNOWN", False),
        ("NO-IDEA", False),
        ("MISSING", False),
    ],
)
def test_looks_like_model(value: str, expected: bool) -> None:
    assert looks_like_model(value) is expected
