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
    r"|disassembl\w*|dismantl\w*|pry\w*|tak(e|ing)\s+off|crack\w*\s+(it\s+)?open"
    r"|get(ting)?\s+(inside|into))"
)
# Verbs that mean disassembly on their own, with no casing noun needed.
_DISMANTLE = (
    r"(disassembl\w*|dismantl\w*|take\s+(it\s+)?apart|taking\s+(it\s+)?apart"
    r"|crack\w*\s+(it\s+)?open|get(ting)?\s+inside)"
)
# Doors, trays and turntables are not casing: "the microwave door won't open" is not a hazard.
_CASING = r"(cover|casing|housing|panel|shell|enclosure|back\s+(panel|cover|plate))"
_OPEN_CASING = (
    r"(\b" + _DISASSEMBLE + r"\b.{0,30}\b" + _CASING + r"\b"
    r"|\btak(e|ing)\s+(\w+\s+){0,2}(cover|casing|housing|panel|shell|back)\s+off\b)"
)
_ELECTRIC = (
    r"(outlet|socket|(?<!drain\s)plug|power\s+cord|cord|wiring|wires?|electrical|electricity"
    r"|power\s+strip|breaker|fuse\s*box|electric(al)?\s+panel|extension\s+(lead|cord))"
)
_WET = r"(water|leak\w*|wet|puddle|flood\w*|spill\w*|drip\w*)"
_GAS = r"(gas|propane|lpg|butane)"

KEYWORD_RULES: dict[HazardSignal, tuple[str, ...]] = {
    "gas_smell": (
        r"\bsmell\w*\b[^.?!]{0,25}\b" + _GAS + r"\b",
        r"\b" + _GAS + r"\s+(smell\w*|odou?r|fumes?|stink\w*)",
        r"\b" + _GAS + r"\s+leak\w*",
        r"\bleak\w*\s+(\w+\s+)?" + _GAS + r"\b(?!\s+(dryer|stove|oven|range|heater|appliance))",
        r"\b(propane|lpg|butane)\b.{0,20}\bleak\w*",
        r"\bgas\s+(in|inside|filling)\s+(the|my|our)\s+"
        r"(room|house|home|kitchen|basement|garage|apartment|flat|air|laundry)",
        r"\brotten\s+eggs?\b",
        r"\bsulf(u|ph)ur\w*\s+smell",
    ),
    "smoke_or_burning": (
        r"\bsmok(e|es|ed|ing|y)\b",
        r"\bburn(ing|t|ed)?\s+(smell|odou?r|plastic|rubber|wire|wires|wiring)\b",
        r"\bsmell\w*\b[^.?!]{0,30}\b(burn\w*|scorch\w*|electrical|melt\w*|hot\s+plastic)",
        r"\b(something|it|that)('s|\s+is|\s+was)?\s+(burn(ing|t)|smoking|melting)\b",
        r"\boverheat\w*",
        r"\bhot\s+(plastic|rubber|wire|wiring|electrical)\b",
        r"\belectrical\s+(smell|odou?r|burn\w*)",
        r"\bscorch\w*",
        r"\b(plastic|wires?|wiring|cord|plug|insulation|cable)\b.{0,15}\bmelt\w*",
        r"\bmelt\w*\b.{0,15}\b(plastic|wires?|wiring|cord|plug|insulation|cable)\b",
        r"\b(on\s+fire|caught\s+fire|flames?|fire(?!\s+up))\b",
    ),
    "sparks": (
        r"\bspark(s|ing|ed|y)?\b",
        r"\barc(s|ing|ed)\b",
        r"\b(electric(al)?\s+)?shock(s|ed|ing)?\b(?!\s+absorb)",
        r"\bzap(s|ped|ping)?\b",
    ),
    "water_near_electric": (
        r"\b" + _WET + r"\b.{0,60}\b" + _ELECTRIC + r"\b",
        r"\b" + _ELECTRIC + r"\b.{0,60}\b" + _WET + r"\b",
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
        r"\bmicrowave\b.{0,40}" + _OPEN_CASING,
        r"\b" + _DISASSEMBLE + r"\b.{0,30}\bmicrowave('?s)?\s+" + _CASING + r"\b",
        _OPEN_CASING + r".{0,40}\bmicrowave\b",
        r"\bmicrowave\b.{0,40}\b" + _DISMANTLE + r"\b",
        r"\b" + _DISMANTLE + r"\b.{0,40}\bmicrowave\b",
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

# DOTALL: `.{0,N}` windows must also span line breaks in multi-line messages.
_FLAGS = re.IGNORECASE | re.DOTALL
_COMPILED = {
    hazard: [re.compile(p, _FLAGS) for p in patterns] for hazard, patterns in KEYWORD_RULES.items()
}
_HV_CATEGORY = re.compile(_OPEN_CASING + "|" + r"\b" + _DISMANTLE + r"\b", _FLAGS)


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
