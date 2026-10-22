# ADR-008: The agent's MCP client: a thin in-process client, code-built action arguments, reply as a tool

- **Status:** Accepted
- **Date:** 2026-10-22
- **Spec:** §7.2–§7.6, §12.1–§12.2, §16.3
- **Amends:** ADR-006 (the `mcp<2` pin no longer depends on `langchain-mcp-adapters`)

## Context

M5-07 connects the journey agent to the MCP servers mounted in the API (ADR-004, ADR-006). The spec planned to load the tools with `langchain-mcp-adapters` and to hand them to the LLM through the step's `tools_allowed`. Implementing it raised five issues:

1. **The adapters do not fit our LLM layer.**
   - `load_mcp_tools` produces LangChain `BaseTool`s, and their schema is the server's raw `inputSchema`, so the LLM would see and fill `user_id`.
   - The adapters have no in-memory connection: the agent would need either a long-lived session shared across tasks or an HTTP loop back into its own `/mcp/` mount.
   - The agent does not use LangChain chat models, so the wrapper adds nothing.
2. **`LLMClient` could not call tools.** It had only `structured()` and `text()`.
3. **Some arguments must not come from the LLM.** `list_slots` needs the user's ZIP code, and `book` needs a slot the user actually picked and an appliance they own.
4. **The model must end with a structured reply** (spec §7.3: at most 3 read-tool calls, then a validated `AgentReply`), on providers with different tool-choice rules.
5. **Evals need isolation.** A booking made in one trial must not be visible to the next.

## Decision

1. **A thin client: `agent/tools.py` `McpToolbox`.**
   - Each call opens an in-memory MCP session (`mcp.shared.memory`) on the API's own FastMCP servers, and closes it in the same task. The servers are stateless (ADR-006).
   - Calls still go through the real protocol and the servers' input and output schemas.
   - Failures come back as `ToolOutcome(ok=False)` and never raise. That covers tool errors, unknown tools, invalid arguments and a 10 s timeout.
2. **Two entry points hold the access rules.**
   - `llm_tools` / `call_llm` serve the responder.
     - They offer only read tools that are both in the step's `tools_allowed` and LLM-callable in `mcp_servers.registry`. Names become `server__tool`, because provider function names cannot contain dots.
     - `user_id` is removed from the schemas the LLM sees and is bound from the conversation on every call.
     - A call to a tool that was not offered is refused, even if it is a write tool that a journey listed.
   - `call_action` serves journey step actions and is the only path to write tools. Their arguments are built by code from the state (`nodes/mcp_actions.py`).
3. **`LLMClient.tool_turn`.**
   - One model turn that may call tools. LiteLLM sends OpenAI-format `tools` with `tool_choice`. `Message` carries `tool_calls` and the `tool` role.
   - The responder's final answer is itself a `reply` tool whose schema is `AgentReply`, so every turn at a step with tools is a tool turn.
   - `tool_choice` is `"auto"`, and the client enforces "must call a tool" by retrying once. Thinking modes (DeepSeek's, Anthropic's extended thinking) reject a forced tool choice. A tool turn that still fails falls back to the plain structured reply, so a provider's tool-calling problem never fails the turn.
   - LiteLLM imports its own MCP proxy bridge whenever `tools` are passed. That bridge needs `mcp>=2` and is not used here, so `tool_turn` passes `_skip_mcp_handler=True`.
   - After 3 data-tool calls only `reply` is offered. An invalid reply falls back to one structured call that sees the results. A supervisor revision reuses the results and calls no tools.
4. **Code fetches booking slots.**
   - `escalate` runs `service_booking.list_slots` as a step action, using the profile's ZIP code and the issue's category. The slots are kept in `AgentState.offered_slots` and shown on a `BookingSlotsCard`.
   - `booking_confirmed` accepts only an offered slot. `escalated_end` books it through code.
   - Booking needs an issue linked to a profile appliance, because `book` takes its id.
   - Code states a successful booking as a fixed line above the reply ("Your technician visit is booked for …", with the time zone), so a blocked reply cannot hide it. If the responder's LLM fails after the booking, that line plus a fixed closing becomes the whole reply, so the turn does not end in an error.
   - Asking for a technician with no journey running starts `troubleshoot`, whose `user_requested_technician` guardrail escalates at once. A journey with that guardrail keeps the request instead of switching.
7. **Writes run once per issue.** A turn can still fail after a write tool ran (any error other than an LLM failure): LangGraph had checkpointed `step_executor`, and a later node raised. The runtime rolls the turn back, but it keeps the records of successful writes (`ToolCall.issue_id`). A write action finds that record and replays it instead of calling the tool again, so a retry neither books twice nor records a repair twice. Known gaps: a write that times out after the server committed is `ok=False` and is not replayed, and a cancelled turn (client disconnect) is not rolled back.
8. **Side questions stay on the side.** A side question's slots (`ask_parts`: "do Whirlpool filters fit?") are not applied to the active issue once its details are collected, so they cannot change its brand or unlink its profile appliance; while they are being collected, they still fill or correct them. For a signed-in user, `my_appliances` and `ask_parts` stay side questions even when they name another appliance ("is my dryer still under warranty?"); a guest's goes to the `my_appliances` journey and its sign-in reply; a how-to about another appliance still starts its own journey, because it needs that appliance's manuals.
5. **Profile context without breaking engine purity.**
   - `load_context` reads the profile and appliances into `AgentState.profile` every turn.
   - A pure `engine/profile.py` links the issue to the single matching appliance and prefills `brand` / `model_number` (`source="profile"`).
   - The link (`appliance_id`) is per issue, so paused issues keep it.
6. **Evals:** each trial gets fresh mock-mode servers with their own stores, on a fixed clock.

## Consequences

- No `langchain-mcp-adapters` dependency. The `mcp<2` pin (ADR-006) stays for now, as a separate choice: the servers use `FastMCP` 1.x.
- The responder makes tool turns at steps with tools (`guide`, `inform` in the tool journeys). Latency and the quality of tool use can only be measured with real models (`evals run --suite tools`).
- Whether a model calls `reply` without being forced to is measured by the `tools` suite. The retry and the structured fallback cover the turns where it does not.
- Tool results are data. The responder and supervisor prompts frame them as such, and their tag-like `<` is neutralized in `tool` messages too, which do not pass through the prompt templates. YouTube titles in real mode are an injection surface, like web pages.
- Known limit: booking slot ids are not bound to an issue. A stale `BookingSlotsCard` could only book a slot the current issue was also offered.
- Guests and unlinked issues keep the "contact the manufacturer" handoff. `my_appliances` gives guests a fixed sign-in reply.

## Alternatives considered

- **`langchain-mcp-adapters` with `tool_interceptors` to inject `user_id`.** It works, but it still needs an HTTP loop or a shared session, and a LangChain wrapper the agent never uses.
- **Letting the LLM call `list_slots`.** The model would need the ZIP code in its context (G-PRIV-01), and the card would depend on the model choosing to call the tool.
- **A separate structured call after the tool loop.** That costs one more call on every turn, even when no tool is needed.
