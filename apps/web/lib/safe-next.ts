/** Where to go after sign-in: only a path on this site, never an open redirect
 * (`//evil.com`, `/\evil.com` and tab-split variants all resolve elsewhere and are refused). */
export function safeNext(next: string | null, origin: string): string {
  if (!next) return "/chat";
  try {
    const url = new URL(next, origin);
    return url.origin === origin ? `${url.pathname}${url.search}` : "/chat";
  } catch {
    return "/chat";
  }
}
