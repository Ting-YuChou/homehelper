"""G-PRIV-01 hook: flag replies that ask for personal data (spec §8.1, used by the supervisor)."""

import re

PERSONAL_DATA_TERMS: dict[str, str] = {
    "address": r"\b(home|street|mailing|postal|your)\s+address\b|\bwhere\s+do\s+you\s+live\b",
    "phone": r"\b(phone|mobile|cell|contact)\s+number\b",
    "email": r"\be-?mail(\s+address)?\b",
    "date_of_birth": r"\b(date\s+of\s+birth|birthday|how\s+old\s+are\s+you)\b",
    "payment": r"\b(credit|debit)\s+card\b|\bcard\s+number\b|\bbank\s+account\b",
    "government_id": r"\b(social\s+security|ssn|passport|driver'?s\s+licen[cs]e)\b",
}
_TERMS = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in PERSONAL_DATA_TERMS.items()}
_REQUEST = re.compile(
    r"\b(share|provide|send|give|tell|enter|confirm|need|what'?s|what\s+is|could\s+you|can\s+you"
    r"|may\s+i)\b",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[^.?!]+[.?!]?")

# Contact details the booking flow may legitimately ask for.
BOOKING_ALLOWED = frozenset({"address", "phone", "email"})


def personal_data_requests(reply_text: str) -> list[str]:
    """Kinds of personal data a reply asks the user for (a question or a request sentence)."""
    asked: set[str] = set()
    for sentence in _SENTENCE.findall(reply_text):
        if not (sentence.rstrip().endswith("?") or _REQUEST.search(sentence)):
            continue
        asked.update(name for name, term in _TERMS.items() if term.search(sentence))
    return sorted(asked)


def check_privacy(reply_text: str, *, booking_in_progress: bool = False) -> list[str]:
    """G-PRIV-01 violations: personal data asked for outside the booking flow."""
    allowed = BOOKING_ALLOWED if booking_in_progress else frozenset()
    return [kind for kind in personal_data_requests(reply_text) if kind not in allowed]
