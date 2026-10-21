# ADR-002: Declarative journeys on a fixed LangGraph pipeline

- **Status:** Accepted
- **Date:** 2026-10-21
- **Spec:** §3 (P1, P2, P7), §7

## Context

In v1 a 3B model chose which tools to call and in what order. Behavior was unpredictable and impossible to debug, and safety policy depended on the model remembering it. A support agent needs flows and policies that are deterministic, testable, and explainable, while still using an LLM to understand free-form user input and to write natural replies.

## Decision

The LLM understands and expresses; code controls flow and policy.

- **Journeys** (`troubleshoot`, `how_to_use`, …) are declarative YAML: slots, typed steps (`collect`, `confirm`, `system`, `guide`, `inform`, `handoff`, `end`), transitions, and guardrails.
- Conditions are **named predicates** registered in Python; YAML cannot contain arbitrary expressions.
- `transition(journey, state, nlu) -> TransitionResult` is a pure function with ≥ 90% test coverage. Journeys are validated at load time: all targets exist, all predicates are registered, an `end` is reachable, and no step is a dead end.
- Each turn runs a **fixed LangGraph graph** (`load_context → process_media → understand → guard_input → route → step_executor → act → respond → supervise → persist_and_emit`). LangGraph provides the node structure, streaming, and durable state via `AsyncPostgresSaver` (`thread_id = conversation_id`).
- Every transition, guardrail hit, and supervisor verdict is written to `decision_log` and to the trace.

## Consequences

- Flows can be unit-tested without an LLM, and every agent decision can be explained from the trace.
- Adding a capability means writing a journey and maybe a predicate, not prompting a model to behave.
- Less flexible than a free-form tool-calling agent for requests no journey covers; those fall back to `out_of_scope` or `inform`.
- We maintain a small DSL, its schema, and its validator.

## Alternatives considered

- **Free-form ReAct/tool-calling agent:** fastest to build, but this is the v1 failure mode.
- **LangGraph graph per journey (no DSL):** flows would live in Python wiring and be harder to review and validate than data.
- **Hand-rolled state machine without LangGraph:** we would have to rebuild checkpointing, streaming, and node tracing ourselves.
