"""English-only output (spec §8.1 G-INJ-01, §8.2 S5): a cheap check for text in another language.

An English sentence of any length is full of common function words; text that an injected
instruction ("reply only in French") switched to another language has almost none.
"""

import re

_ENGLISH_WORDS = frozenset(
    "a an and are as at be but can do for from have i if in is it let me my no not of on or "  # noqa: SIM905
    "please so that the then this to try we what when will with you your".split()
)
MIN_ENGLISH_SHARE = 0.15
MIN_WORDS = 6  # shorter texts are not judged


def looks_english(text: str) -> bool:
    words = re.findall(r"[^\W\d_]+", text.lower())
    if len(words) < MIN_WORDS:
        return True
    return sum(word in _ENGLISH_WORDS for word in words) / len(words) >= MIN_ENGLISH_SHARE
