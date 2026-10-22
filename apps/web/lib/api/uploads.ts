// POST /v1/uploads (spec §11.1). Multipart, so it uses fetch directly rather than openapi-fetch.
import { API_URL } from "./client";
import type { Attachment } from "./types";

export class UploadError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export async function uploadFile(file: File, fetcher: typeof fetch = fetch): Promise<Attachment> {
  const body = new FormData();
  body.append("file", file);
  let response: Response;
  try {
    response = await fetcher(`${API_URL}/v1/uploads`, {
      method: "POST",
      body,
      credentials: "include",
    });
  } catch {
    throw new UploadError("network_error", "Couldn't upload. Check your connection and try again.");
  }
  if (response.ok) return (await response.json()) as Attachment;
  const error = (await response.json().catch(() => ({}))) as { code?: string; detail?: unknown };
  const message =
    typeof error.detail === "string" ? error.detail : "That file couldn't be uploaded.";
  throw new UploadError(error.code ?? "upload_failed", message);
}
