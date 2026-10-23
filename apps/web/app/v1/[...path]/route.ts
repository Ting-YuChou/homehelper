import type { NextRequest } from "next/server";

import { requestHeaders, responseHeaders, upstreamUrl } from "@/lib/proxy/headers";

// Streams every `/v1` request to the API and its response (SSE included) back, so the browser
// only ever talks to the web origin (ADR-011). Read at request time: one image for every
// environment.
async function proxy(request: NextRequest, ctx: RouteContext<"/v1/[...path]">): Promise<Response> {
  const { path } = await ctx.params;
  const target = upstreamUrl(
    process.env.API_URL ?? "http://localhost:8000",
    path,
    request.nextUrl.search,
  );
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers: requestHeaders(request.headers, process.env.PROXY_SECRET ?? ""),
      body: hasBody ? request.body : undefined,
      // Uploads stream through instead of being buffered here.
      duplex: "half",
      redirect: "manual",
      cache: "no-store",
      // A visitor who leaves cancels the upstream request; the API finishes the turn anyway.
      signal: request.signal,
    } as RequestInit);
  } catch (error) {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    // One JSON line, so Cloud Logging reads its severity.
    console.error(
      JSON.stringify({ severity: "ERROR", event: "proxy_failed", path: path.join("/"), error: String(error) }),
    );
    return Response.json({ detail: "The service is unavailable. Please try again." }, { status: 502 });
  }
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders(upstream.headers),
  });
}

export { proxy as DELETE, proxy as GET, proxy as PATCH, proxy as POST, proxy as PUT };
