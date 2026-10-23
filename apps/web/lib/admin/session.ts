/** What to tell an admin whose sign-in got this HTTP status. */
export function signInMessage(status: number): string {
  if (status === 401) return "That admin token isn't right.";
  if (status === 429) return "Too many attempts. Try again in an hour.";
  if (status === 403) return "This page isn't allowed to sign in to the API.";
  return "Can't reach the HomeHelper API right now.";
}
