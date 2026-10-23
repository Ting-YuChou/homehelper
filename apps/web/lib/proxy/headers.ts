// The web app's `/v1` proxy (ADR-011, spec Q11): browsers only ever talk to the web origin, so the
// API's session cookies are first-party on Cloud Run, where web and API are separate `run.app`
// sites. These helpers decide what crosses the proxy in each direction.

// Hop-by-hop headers (RFC 9110 §7.6.1) and ones the upstream fetch sets itself.
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "proxy-connection",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  // curl sends it for large uploads; Node's fetch refuses to forward it.
  "expect",
]);
// Ours to set: a visitor's own copies are dropped. The API reads the visitor's IP from
// X-HH-Client-IP only when it comes with the shared secret.
const CLIENT_IP = "x-hh-client-ip";
const PROXY_SECRET = "x-hh-proxy-secret";
const DROPPED_REQUEST = new Set([...HOP_BY_HOP, "x-forwarded-for", CLIENT_IP, PROXY_SECRET]);
// fetch hands us a decoded body, so its encoding and length no longer apply.
const DROPPED_RESPONSE = new Set([...HOP_BY_HOP, "content-encoding", "content-length", "set-cookie"]);

/** `<api>/v1/<path>?<query>`. A segment made only of dots is escaped so it can't climb out of
 * `/v1` when the URL is normalized. */
export function upstreamUrl(apiUrl: string, path: string[], search: string): string {
  const segments = path.map((segment) =>
    /^\.+$/.test(segment) ? segment.replaceAll(".", "%2E") : encodeURIComponent(segment),
  );
  return `${apiUrl.replace(/\/+$/, "")}/v1/${segments.join("/")}${search}`;
}

/** The visitor's address: Cloud Run appends the connecting IP to X-Forwarded-For, so the last
 * entry is the one a visitor can't forge. */
export function clientIp(headers: Headers): string | null {
  const forwarded = headers.get("x-forwarded-for");
  const last = forwarded?.split(",").at(-1)?.trim();
  return last || null;
}

export function requestHeaders(incoming: Headers, secret: string): Headers {
  const out = new Headers();
  incoming.forEach((value, name) => {
    if (!DROPPED_REQUEST.has(name)) out.set(name, value);
  });
  const ip = clientIp(incoming);
  if (secret && ip) {
    out.set(CLIENT_IP, ip);
    out.set(PROXY_SECRET, secret);
  }
  return out;
}

export function responseHeaders(upstream: Headers): Headers {
  const out = new Headers();
  upstream.forEach((value, name) => {
    if (!DROPPED_RESPONSE.has(name)) out.set(name, value);
  });
  // forEach would join several Set-Cookie headers into one; copy them one by one.
  for (const cookie of upstream.getSetCookie()) out.append("set-cookie", cookie);
  // SSE: ask any buffering proxy in front of us to pass chunks straight through.
  out.set("x-accel-buffering", "no");
  return out;
}
