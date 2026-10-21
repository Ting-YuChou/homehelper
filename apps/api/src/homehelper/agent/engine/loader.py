"""Load journey YAML and validate it at startup (spec §7.4). Any problem raises before serving."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml
from pydantic import ValidationError

from homehelper.agent.engine.predicates import PREDICATES, PredicateRegistry
from homehelper.agent.engine.schema import KNOWN_ACTIONS, MCP_TOOL, Journey, is_write_tool
from homehelper.agent.guardrails.templates import STEP_TEMPLATES
from homehelper.agent.state import Intent
from homehelper.knowledge.schemas import CategoryId

DEFAULT_JOURNEYS_DIR = Path(__file__).resolve().parent.parent / "journeys"

# Named value sets an enum slot can reference with `values: <name>`.
VALUE_SETS: dict[str, tuple[str, ...]] = {"categories": tuple(c.value for c in CategoryId)}


class JourneyValidationError(ValueError):
    def __init__(self, source: str, errors: list[str]) -> None:
        self.source = source
        self.errors = errors
        details = "\n".join(f"  - {error}" for error in errors)
        super().__init__(f"invalid journey {source}:\n{details}")


def slot_values(values: str | list[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        return VALUE_SETS[values]
    return tuple(values)


def validate_journey(journey: Journey, predicates: PredicateRegistry = PREDICATES) -> list[str]:
    """Graph-level checks the schema cannot express. Returns error messages (empty = valid)."""
    errors: list[str] = []
    step_ids = [step.id for step in journey.steps]
    known = set(step_ids)

    for step_id in sorted({s for s in step_ids if step_ids.count(s) > 1}):
        errors.append(f"duplicate step id {step_id!r}")
    if journey.entry is not None and journey.entry not in known:
        errors.append(f"entry step {journey.entry!r} does not exist")

    for name, spec in journey.slots.items():
        if isinstance(spec.values, str) and spec.values not in VALUE_SETS:
            errors.append(f"slot {name!r}: unknown value set {spec.values!r}")

    def check_predicate(name: str, where: str) -> None:
        if name not in predicates:
            errors.append(f"{where}: predicate {name!r} is not registered")

    for i, guard in enumerate(journey.guardrails):
        check_predicate(guard.when, f"guardrails[{i}]")
        if guard.to not in known:
            errors.append(f"guardrails[{i}]: target {guard.to!r} does not exist")

    for step in journey.steps:
        where = f"step {step.id!r}"
        if step.skip_when:
            check_predicate(step.skip_when, f"{where} skip_when")
        for t in step.transitions:
            check_predicate(t.when, where)
            if t.to not in known:
                errors.append(f"{where}: target {t.to!r} does not exist")
        for action in step.actions:
            if action not in KNOWN_ACTIONS and not MCP_TOOL.match(action):
                errors.append(f"{where}: unknown action {action!r}")
        for tool in step.tools_allowed:
            if not MCP_TOOL.match(tool):
                errors.append(f"{where}: tools_allowed entry {tool!r} is not mcp:<server>.<tool>")
            elif is_write_tool(tool):
                errors.append(
                    f"{where}: write tool {tool!r} cannot be exposed to the LLM; "
                    "call it from a step action instead"
                )
        if step.template is not None and step.template not in STEP_TEMPLATES:
            errors.append(f"{where}: unknown template {step.template!r}")

    if errors:  # graph checks below assume ids and targets are sound
        return errors

    edges = _edges(journey)
    reachable = _reachable(journey.entry_step, edges)
    for step_id in step_ids:
        if step_id not in reachable:
            errors.append(f"step {step_id!r} is unreachable from entry {journey.entry_step!r}")
    ends = {step.id for step in journey.steps if step.type == "end"}
    if not ends & reachable:
        errors.append(f"no end step is reachable from entry {journey.entry_step!r}")
    for step_id in step_ids:
        if not ends & _reachable(step_id, edges):
            errors.append(f"step {step_id!r} cannot reach any end step")
    return errors


def _edges(journey: Journey) -> dict[str, set[str]]:
    guard_targets = {guard.to for guard in journey.guardrails}
    edges: dict[str, set[str]] = {}
    for step in journey.steps:
        if step.type == "end":
            edges[step.id] = set()
        else:
            edges[step.id] = {t.to for t in step.transitions} | guard_targets
    return edges


def _reachable(start: str, edges: dict[str, set[str]]) -> set[str]:
    seen = {start}
    stack = [start]
    while stack:
        for nxt in edges[stack.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def parse_journey(
    data: object, source: str = "<data>", predicates: PredicateRegistry = PREDICATES
) -> Journey:
    try:
        journey = Journey.model_validate(data)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(part) for part in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()
        ]
        raise JourneyValidationError(source, errors) from exc
    errors = validate_journey(journey, predicates)
    if errors:
        raise JourneyValidationError(source, errors)
    return journey


def load_journey(path: Path, predicates: PredicateRegistry = PREDICATES) -> Journey:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise JourneyValidationError(str(path), [f"YAML syntax: {exc}"]) from exc
    return parse_journey(data, str(path), predicates)


@dataclass(frozen=True)
class JourneyCatalog:
    """Loaded journeys by id. `hazard_journey` handles a hazard when no journey is running."""

    journeys: dict[str, Journey]
    hazard_journey: str = "troubleshoot"
    _by_intent: dict[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        errors: list[str] = []
        by_intent: dict[str, str] = {}
        for journey in self.journeys.values():
            for intent in journey.entry_intents:
                if intent in by_intent:
                    errors.append(
                        f"intent {intent!r} is an entry intent of both "
                        f"{by_intent[intent]!r} and {journey.id!r}"
                    )
                by_intent[intent] = journey.id
        if self.hazard_journey not in self.journeys:
            errors.append(f"hazard journey {self.hazard_journey!r} is not loaded")
        elif "hazard_detected" not in {
            g.when for g in self.journeys[self.hazard_journey].guardrails
        }:
            errors.append(
                f"hazard journey {self.hazard_journey!r} has no hazard_detected guardrail"
            )
        if errors:
            raise JourneyValidationError("catalog", errors)
        object.__setattr__(self, "_by_intent", by_intent)

    @classmethod
    def from_journeys(cls, journeys: Iterable[Journey], **kwargs: str) -> "JourneyCatalog":
        mapping: dict[str, Journey] = {}
        for journey in journeys:
            if journey.id in mapping:
                raise JourneyValidationError("catalog", [f"duplicate journey id {journey.id!r}"])
            mapping[journey.id] = journey
        return cls(journeys=mapping, **kwargs)

    def __getitem__(self, journey_id: str) -> Journey:
        return self.journeys[journey_id]

    def for_intent(self, intent: Intent | None) -> Journey | None:
        if intent is None or intent not in self._by_intent:
            return None
        return self.journeys[self._by_intent[intent]]


def load_catalog(
    directory: Path = DEFAULT_JOURNEYS_DIR, predicates: PredicateRegistry = PREDICATES
) -> JourneyCatalog:
    paths = sorted(directory.glob("*.yaml"))
    if not paths:
        raise JourneyValidationError(str(directory), ["no journey files found"])
    return JourneyCatalog.from_journeys(load_journey(path, predicates) for path in paths)


@cache
def default_catalog() -> JourneyCatalog:
    """The packaged journeys; call at app startup so invalid YAML fails fast."""
    return load_catalog()
