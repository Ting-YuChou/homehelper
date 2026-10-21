import { createParser } from "eventsource-parser";

import { API_URL } from "./client";
import type { AgentEvent, ErrorEvent, SendMessageBody } from "./types";

const NETWORK_ERROR: ErrorEvent = {
  type: "error",
  code: "network_error",
  message: "Couldn't reach HomeHelper. Check your connection and try again.",
};

/** Read an SSE body, calling `onEvent` for each event (heartbeat comments are dropped). */
export async function readEvents(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: AgentEvent) => void,
): Promise<void> {
  const parser = createParser({
    onEvent(message) {
      onEvent(JSON.parse(message.data) as AgentEvent);
    },
  });
  const reader = body.getReader();
  const decoder = new TextDecoder();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parser.feed(decoder.decode(value, { stream: true }));
  }
  parser.feed(decoder.decode());
}

/**
 * POST a message and stream the agent's events (spec §13.3). The browser `EventSource` only
 * does GET, so this reads the response body with fetch. Refusals (rate limit, maintenance, busy)
 * arrive as an `error` event; other HTTP errors are turned into one.
 */
export async function streamMessage(
  conversationId: string,
  body: SendMessageBody,
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/v1/conversations/${conversationId}/messages`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) return;
    onEvent(NETWORK_ERROR);
    throw error;
  }
  const isStream = response.headers.get("content-type")?.startsWith("text/event-stream");
  if (isStream && response.body) {
    try {
      await readEvents(response.body, onEvent);
    } catch (error) {
      if (signal?.aborted) return;
      onEvent(NETWORK_ERROR); // the connection dropped mid-turn
      throw error;
    }
    return;
  }
  const detail = await response
    .json()
    .then((json: { detail?: unknown }) => json.detail)
    .catch(() => undefined);
  onEvent({
    type: "error",
    code: response.status === 401 ? "unauthorized" : `http_${response.status}`,
    message: typeof detail === "string" ? detail : "Something went wrong. Please try again.",
  });
}
