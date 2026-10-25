"""Two-layer hazard detection (spec §8.1): English keyword rules OR NLU `hazard_signals`.

Either layer alone triggers. The keyword rules deliberately over-match (negations such as
"no smoke" still trigger): a false positive costs one cautious reply, a miss can cost far more.
"""

import re
from typing import Literal, get_args

from pydantic import BaseModel

from homehelper.agent.state import AgentState, HazardSignal

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
        # Sealed-system repairs (G-SAFE-04): cutting or brazing lines, swapping the compressor.
        r"\bcapillary\s+tubes?\b",
        r"\bbraz(e|es|ed|ing)\b",
        r"\b(replac\w*|swap\w*|install\w*)\b.{0,60}\bcompressor\b",
        r"\bcompressor\b.{0,60}\b(replac\w*|swap\w*)\b",
        r"\bre-?seal\w*\s+(the\s+)?(system|lines?|tubing)\b",
        r"\b(evaporator|condenser)\b.{0,30}\b(leak\w*|punctur\w*|hiss\w*)",
        r"\bpunctur\w*\b.{0,30}\b(evaporator|condenser)\b",
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
        # Getting a shock is an injury (G-SAFE-07) as well as a sign of live parts (sparks).
        r"\b(got|get|getting)\s+(an?\s+)?(electric(al)?\s+)?shock\b",
    ),
}

# Opening the casing of these appliances exposes high-voltage parts (G-SAFE-03).
HIGH_VOLTAGE_CATEGORIES = frozenset({"microwave", "television"})

# Hazards whose fixed reply tells the user to cut the power or not to touch switches; once one
# was flagged for an appliance, none of its plan steps may need the power back on (G-SAFE-08).
POWER_OFF_HAZARDS: frozenset[HazardSignal] = frozenset(
    {"water_near_electric", "smoke_or_burning", "sparks", "gas_smell"}
)
ANY_APPLIANCE = "*"  # a gas smell: no switches anywhere in the home
UNASSIGNED = "unassigned"  # reported before any issue: the next issue takes it


def issue_key(issue_id: str) -> str:
    return f"issue:{issue_id}"


def issue_power_off(state: AgentState) -> list[str]:
    """The power-off hazards that apply to the active issue: its own, those of other issues
    about the same appliance (as their records say now, so a corrected appliance doesn't
    carry a stale hazard), those reported about its appliance by name, and gas."""
    category_slot = state.slots.get("appliance_category")
    category = category_slot.value if category_slot else None
    keys = {ANY_APPLIANCE}
    if state.active_issue_id:
        keys.add(issue_key(state.active_issue_id))
    if category:
        keys.add(category)
        keys.update(
            issue_key(record.issue_id)
            for record in state.issues
            if record.issue_id != state.active_issue_id and record.appliance_category == category
        )
    return sorted({signal for key in keys for signal in state.power_off.get(key, [])})


# DOTALL: `.{0,N}` windows must also span line breaks in multi-line messages.
_FLAGS = re.IGNORECASE | re.DOTALL
_COMPILED = {
    hazard: [re.compile(p, _FLAGS) for p in patterns] for hazard, patterns in KEYWORD_RULES.items()
}
_HV_CATEGORY = re.compile(_OPEN_CASING + "|" + r"\b" + _DISMANTLE + r"\b", _FLAGS)


class HazardHit(BaseModel):
    signal: HazardSignal
    source: Literal["keywords", "nlu", "media", "both"]


# The user says the water is *still* reaching electricity after the G-SAFE-05 warning ("still
# dripping onto the outlet", "the power strip is still in the water"). One clause must hold a
# persistence cue, a wet term and an electric term, so "the breaker is off, but there's still
# standing water in the tub" (the symptom) or "I mopped up the water" (the warning was followed)
# does not count.
_CLAUSES = re.compile(r"[.;!?]+|\bbut\b", re.I)
# Getting worse ("spraying", "spreading") counts as persisting too.
_CUE = re.compile(
    r"\b(still|keeps?|continu\w*|again|(hasn'?t|has not|have not|never) (gone|dried|stopped)"
    r"|(won'?t|will not) (dry|stop)"
    r"|worse|spray\w*|spread\w*|gush\w*)\b",
    re.I,
)
_NOT_A_CUE = re.compile(r"\bstill (off|unplugged|disconnected|switched off|turned off)\b", re.I)
_WET_HERE = re.compile(r"\b(" + _WET[1:-1] + r"|pool\w*|soak\w*|sitting in)\b", re.I)
_ELECTRIC_HERE = re.compile(r"\b" + _ELECTRIC + r"\b", re.I)
_RESOLVED = re.compile(
    r"\b(no longer|not (wet|leaking|dripping|pooling) anymore|(is|are) (gone|dry)"
    r"|(?<!n't )(?<!nt )(?<!not )(?<!never )stopped)\b",
    re.I,
)


def _plain(text: str) -> str:
    """Typographic apostrophes (phone keyboards send them) as ASCII, so `hasn't` matches."""
    return text.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'").replace(
        "\N{LEFT SINGLE QUOTATION MARK}", "'"
    )


def water_persists(text: str | None) -> bool:
    """Whether the user reports water still reaching electricity (spec §8.1 G-SAFE-05)."""
    for clause in _CLAUSES.split(_plain(text or "")):
        cue = _CUE.search(_NOT_A_CUE.sub("", clause))
        wet_electric = _WET_HERE.search(clause) and _ELECTRIC_HERE.search(clause)
        if cue and wet_electric and not _RESOLVED.search(clause):
            return True
    return False


def keyword_hazards(text: str | None, *, category: str | None = None) -> list[HazardSignal]:
    """Hazards matched by the English keyword rules, in `HazardSignal` order."""
    if not text:
        return []
    text = _plain(text)
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
    media_signals: list[HazardSignal] | None = None,
) -> list[HazardHit]:
    """Union of both layers, plus what a photo or video showed; any one triggers."""
    by_keywords = set(keyword_hazards(text, category=category))
    by_nlu = set(nlu_signals or [])
    by_media = set(media_signals or [])
    hits: list[HazardHit] = []
    for hazard in _ALL_HAZARDS:
        if hazard in by_keywords and hazard in by_nlu:
            hits.append(HazardHit(signal=hazard, source="both"))
        elif hazard in by_keywords:
            hits.append(HazardHit(signal=hazard, source="keywords"))
        elif hazard in by_nlu:
            hits.append(HazardHit(signal=hazard, source="nlu"))
        elif hazard in by_media:
            hits.append(HazardHit(signal=hazard, source="media"))
    return hits
