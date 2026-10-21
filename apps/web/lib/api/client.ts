import createClient from "openapi-fetch";

import type { paths } from "./schema";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// The session is an httpOnly cookie set by the API, so every request sends credentials.
export const api = createClient<paths>({ baseUrl: API_URL, credentials: "include" });

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Unwrap an openapi-fetch result, throwing `ApiError` for non-2xx responses. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok) {
    const detail = (error as { detail?: unknown } | undefined)?.detail;
    throw new ApiError(response.status, typeof detail === "string" ? detail : response.statusText);
  }
  return data as T;
}
