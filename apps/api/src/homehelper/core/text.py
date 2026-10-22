"""Text helpers shared by the prompt builders."""

import re

_TAG = re.compile(r"<(?=/?[A-Za-z])")
# A look-alike of `<` that no tag parser reads as one.
ANGLE_QUOTE = "\N{SINGLE LEFT-POINTING ANGLE QUOTATION MARK}"


def neutralize_tags(text: str) -> str:
    """Untrusted text cannot open or close a prompt's delimiter tags (`</user_message>`,
    `<excerpt ...>`): their `<` becomes an angle quote. A plain `<` ("< 5 mm") is left alone."""
    return _TAG.sub(ANGLE_QUOTE, text)
