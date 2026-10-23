import { describe, expect, it, vi } from "vitest";

import { UploadError, uploadFile } from "./uploads";

const ATTACHMENT = {
  id: "att_1",
  kind: "image",
  mime: "image/jpeg",
  size: 1234,
  width: 800,
  height: 600,
  duration_s: null,
  status: "ready",
  created_at: "2026-10-22T10:00:00Z",
};

function respond(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("uploadFile", () => {
  it("posts the file as multipart `file` with the session cookie", async () => {
    const fetcher = vi.fn().mockResolvedValue(respond(201, ATTACHMENT));
    const photo = new File(["jpeg"], "IMG_1.jpg", { type: "image/jpeg" });
    const attachment = await uploadFile(photo, fetcher);
    expect(attachment.id).toBe("att_1");
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toMatch(/\/v1\/uploads$/);
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect((init.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it.each([
    [413, "too_large", "Videos can be up to 30 MB."],
    [415, "unsupported_type", "Send a photo or a video."],
    [422, "too_long", "Videos can be up to 60 seconds long."],
    [429, "rate_limited", "You've uploaded a lot of files."],
  ])("shows the API's reason for %i", async (status, code, detail) => {
    const fetcher = vi.fn().mockResolvedValue(respond(status, { code, detail }));
    const error = await uploadFile(new File(["x"], "x.jpg"), fetcher).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(UploadError);
    expect((error as UploadError).message).toBe(detail);
    expect((error as UploadError).code).toBe(code);
  });

  it("has a message for network failures", async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    const error = await uploadFile(new File(["x"], "x.jpg"), fetcher).catch((e: unknown) => e);
    expect((error as UploadError).code).toBe("network_error");
  });
});
