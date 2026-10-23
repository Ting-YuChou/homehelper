/** What to tell someone whose demo sign-in failed, by the API's status code. */
export function loginMessage(status: number, codeRequired: boolean): string {
  if (status === 403 && codeRequired) return "That access code isn't right.";
  if (status === 429) return "Too many sign-ins. Try again in an hour.";
  return "Couldn't sign in. Is the API running?";
}
