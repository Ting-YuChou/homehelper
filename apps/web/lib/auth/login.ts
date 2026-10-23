import { ApiError } from "@/lib/api/client";

/** The API's `detail` for a missing or wrong demo access code (`api/auth.py`). */
export const WRONG_CODE = "Wrong access code";

/** Whether a failed sign-in was refused for its access code (not, say, the Origin check). */
export function isWrongCode(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403 && error.message === WRONG_CODE;
}

/** What to tell someone whose demo sign-in failed. */
export function loginMessage(error: unknown): string {
  if (isWrongCode(error)) return "That access code isn't right.";
  const status = error instanceof ApiError ? error.status : 0;
  if (status === 429) return "Too many sign-ins. Try again in an hour.";
  return "Couldn't sign in. Is the API running?";
}
