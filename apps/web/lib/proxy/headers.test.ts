import { describe, expect, it } from "vitest";

import { clientIp, requestHeaders, responseHeaders, upstreamUrl } from "./headers";

describe("upstreamUrl", () => {
  it("joins the API origin, the /v1 path and the query", () => {
    expect(upstreamUrl("http://api:8000", ["conversations", "c1", "messages"], "")).toBe(
      "http://api:8000/v1/conversations/c1/messages",
    );
    expect(upstreamUrl("https://api.example/", ["admin", "evals"], "?suite=full")).toBe(
      "https://api.example/v1/admin/evals?suite=full",
    );
  });

  it("re-encodes path segments, so a segment cannot climb out of /v1", () => {
    expect(upstreamUrl("http://api:8000", ["..", "healthz"], "")).toBe(
      "http://api:8000/v1/%2E%2E/healthz",
    );
    expect(upstreamUrl("http://api:8000", ["a/b"], "")).toBe("http://api:8000/v1/a%2Fb");
  });
});

describe("clientIp", () => {
  it("takes the address Cloud Run appended: the last X-Forwarded-For entry", () => {
    expect(clientIp(new Headers({ "x-forwarded-for": "6.6.6.6, 203.0.113.7" }))).toBe(
      "203.0.113.7",
    );
    expect(clientIp(new Headers())).toBeNull();
  });
});

describe("requestHeaders", () => {
  const incoming = new Headers({
    cookie: "hh_session=abc",
    origin: "https://web.example",
    "content-type": "application/json",
    "content-length": "12",
    host: "web.example",
    connection: "keep-alive",
    expect: "100-continue",
    "x-forwarded-for": "6.6.6.6, 203.0.113.7",
    "x-hh-client-ip": "1.1.1.1",
    "x-hh-proxy-secret": "guess",
  });

  it("forwards the browser's headers and vouches for its IP with the secret", () => {
    const out = requestHeaders(incoming, "s3cret");
    expect(out.get("cookie")).toBe("hh_session=abc");
    expect(out.get("origin")).toBe("https://web.example");
    expect(out.get("content-length")).toBe("12");
    expect(out.get("x-hh-client-ip")).toBe("203.0.113.7");
    expect(out.get("x-hh-proxy-secret")).toBe("s3cret");
    for (const name of ["host", "connection", "expect", "x-forwarded-for"]) {
      expect(out.has(name)).toBe(false);
    }
  });

  it("never passes on a visitor's own X-HH headers", () => {
    const out = requestHeaders(incoming, "");
    expect(out.has("x-hh-client-ip")).toBe(false);
    expect(out.has("x-hh-proxy-secret")).toBe(false);
  });
});

describe("responseHeaders", () => {
  it("keeps every Set-Cookie and drops what no longer describes the body", () => {
    const upstream = new Headers({
      "content-type": "text/event-stream",
      "content-encoding": "gzip",
      "content-length": "100",
      "x-request-id": "ab",
    });
    upstream.append("set-cookie", "hh_session=1; Path=/; HttpOnly");
    upstream.append("set-cookie", "hh_admin=2; Path=/; HttpOnly");
    const out = responseHeaders(upstream);
    expect(out.getSetCookie()).toEqual([
      "hh_session=1; Path=/; HttpOnly",
      "hh_admin=2; Path=/; HttpOnly",
    ]);
    expect(out.get("content-type")).toBe("text/event-stream");
    expect(out.get("x-request-id")).toBe("ab");
    expect(out.has("content-encoding")).toBe(false);
    expect(out.has("content-length")).toBe(false);
    expect(out.get("x-accel-buffering")).toBe("no");
  });
});
