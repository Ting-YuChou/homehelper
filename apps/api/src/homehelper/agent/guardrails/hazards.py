"""Two-layer hazard detection (spec §8.1): English keyword rules OR NLU `hazard_signals`.

Either layer alone triggers. The keyword rules deliberately over-match (negations such as
"no smoke" still trigger): a false positive costs one cautious reply, a miss can cost far more.
"""

import re
from typing import Literal, get_args

from pydantic import BaseModel

from homehelper.agent.state import HazardSignal

_ALL_HAZARDS: tuple[HazardSignal, ...] = get_args(HazardSignal)

_DISASSEMBLE = (
    r"(open(ing)?|remov(e|ing)|unscrew\w*|take\s+(it\s+|the\s+\w+\s+)?apart|taking\s+\w*\s*apart"
    r"|disassembl\w*|pry\w*|tak(e|ing)\s+off)"
)
_CASING = r"(cover|casing|case|housing|panel|back|shell|enclosure)"

KEYWORD_RULES: dict[HazardSignal, tuple[str, ...]] = {
    "gas_smell": (
        r"\bsmell\w*\s+(of\s+|like\s+)?(natural\s+|propane\s+)?gas\b",
        r"\bgas\s+(smell|odou?r|leak\w*)",
        r"\bgas\b.{0,30}\bleak\w*",
        r"\bleak\w*\s+gas\b",
        r"\brotten\s+eggs?\b",
        r"\bsulf(u|ph)ur\w*\s+smell",
    ),
    "smoke_or_burning": (
        r"\bsmok(e|es|ed|ing|y)\b",
        r"\bburn(ing|t|ed)?\s+(smell|odou?r|plastic|rubber|wire|wires|wiring)\b",
        r"\bsmell\w*\s+(of\s+|like\s+)?(something\s+)?(burn\w*|melt\w*|scorch\w*|electrical)",
        r"\bscorch\w*",
        r"\bmelt(ed|ing|s)?\b",
        r"\b(on\s+fire|caught\s+fire|flames?|fire(?!\s+up))\b",
    ),
    "sparks": (
        r"\bspark(s|ing|ed|y)?\b",
        r"\barc(s|ing|ed)\b",
        r"\b(electric(al)?\s+)?shock(s|ed|ing)?\b(?!\s+absorb)",
        r"\bzap(s|ped|ping)?\b",
    ),
    "water_near_electric": (
        r"\b(water|leak\w*|wet|puddle|flood\w*|spill\w*|drip\w*)\b.{0,60}"
        r"\b(outlet|socket|(?<!drain\s)plug|power\s+cord|cord|wiring|wires?|electrical"
        r"|power\s+strip|breaker|extension\s+lead|extension\s+cord)\b",
        r"\b(outlet|socket|(?<!drain\s)plug|power\s+cord|cord|wiring|wires?|electrical"
        r"|power\s+strip|extension\s+lead|extension\s+cord)\b.{0,60}\b(water|wet|puddle|flood\w*|leak\w*)\b",
    ),
    "refrigerant": (
        r"\brefrigerant\b",
        r"\bfreon\b",
        r"\bcoolant\b",
        r"\bsealed\s+system\b",
        r"\bcompressor\b.{0,40}\b(leak\w*|hiss\w*|oil)\b",
        r"\b(re-?gas|recharg\w*)\b.{0,30}\b(fridge|refrigerator|freezer|gas)\b",
    ),
    "high_voltage_internal": (
        r"\bmagnetron\b",
        r"\bhigh[\s-]?voltage\b",
        r"\bcapacitor\b",
        r"\bmicrowave\b.{0,40}\b" + _DISASSEMBLE + r"\b",
        r"\b" + _DISASSEMBLE + r"\b.{0,40}\bmicrowave\b",
    ),
    "injury": (
        r"\bhurt\s+(my|myself)\b",
        r"\binjur(ed|y|ies)\b",
        r"\bbleed\w*\b",
        r"\belectrocut\w*",
        r"\b(burn(ed|t)?|cut)\s+(my|myself)\b",
        r"\bgot\s+(shocked|burned|burnt|hurt|cut)\b",
    ),
}

# Opening the casing of these appliances exposes high-voltage parts (G-SAFE-03).
HIGH_VOLTAGE_CATEGORIES = frozenset({"microwave", "television"})
_HV_CATEGORY_RULE = r"\b" + _DISASSEMBLE + r"\b.{0,30}\b" + _CASING + r"\b"

_COMPILED = {
    hazard: [re.compile(p, re.IGNORECASE) for p in patterns]
    for hazard, patterns in KEYWORD_RULES.items()
}
_HV_CATEGORY = re.compile(_HV_CATEGORY_RULE, re.IGNORECASE)


class HazardHit(BaseModel):
    signal: HazardSignal
    source: Literal["keywords", "nlu", "both"]


def keyword_hazards(text: str | None, *, category: str | None = None) -> list[HazardSignal]:
    """Hazards matched by the English keyword rules, in `HazardSignal` order."""
    if not text:
        return []
    found = {
        hazard for hazard, patterns in _COMPILED.items() if any(p.search(text) for p in patterns)
    }
    if category in HIGH_VOLTAGE_CATEGORIES and _HV_CATEGORY.search(text):
        found.add("high_voltage_internal")
    return [hazard for hazard in _ALL_HAZARDS if hazard in found]


def detect_hazards(
    text: str | None,
    nlu_signals: list[HazardSignal] | None = None,
    *,
    category: str | None = None,
) -> list[HazardHit]:
    """Union of both layers; either one triggers."""
    by_keywords = set(keyword_hazards(text, category=category))
    by_nlu = set(nlu_signals or [])
    hits: list[HazardHit] = []
    for hazard in _ALL_HAZARDS:
        if hazard in by_keywords and hazard in by_nlu:
            hits.append(HazardHit(signal=hazard, source="both"))
        elif hazard in by_keywords:
            hits.append(HazardHit(signal=hazard, source="keywords"))
        elif hazard in by_nlu:
            hits.append(HazardHit(signal=hazard, source="nlu"))
    return hits
