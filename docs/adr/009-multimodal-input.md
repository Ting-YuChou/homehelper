# ADR-009: Multimodal input: cleaned uploads, photos as unconfirmed slots, video within the turn

- **Status:** Accepted
- **Date:** 2026-10-22
- **Spec:** §11, §13.2–§13.3, §14.1, §18.1

## Context

M6 lets users send photos and videos. Spec §11 asks for four things: validated uploads with EXIF
removed, a vision call whose result becomes slots (confirmed below 0.7), Gemini for video with an
"analyzing" status and a 60 s timeout, and an eval set. Implementing them raised these questions:

1. Where uploads live, and how a browser reads a private file.
2. How a photo reaches the journey engine without making `transition()` impure.
3. How much a photo is allowed to change: what the user typed, a profile prefill, the appliance
   being worked on.
4. When a video is analyzed, given Cloud Run's request model.
5. How text in an image (a nameplate, a sticker) is kept from steering the agent.
6. What to measure, with images that can't go into git.

## Decision

1. **Uploads are cleaned before they are stored.**
   - **Type:** `POST /v1/uploads` decides the type from the bytes (`filetype`), never the name:
     JPEG, PNG, WebP and HEIC up to 10 MB; MP4, MOV and WebM up to 100 MB and 60 s.
   - **Images:** decoded and re-encoded after applying the EXIF orientation, so no metadata
     survives (EXIF, GPS, ICC, PNG text). The long edge is capped at 1568 px. HEIC becomes JPEG
     (`pi-heif`, decode-only). Decompression bombs and corrupt files are refused.
   - **Videos:** remuxed with PyAV, so the streams are copied, not re-encoded, into a container
     without the original's tags. The 60 s limit is checked against the header, then against
     the span of each stream's packet timestamps while remuxing, so a header can't understate
     the length the models would bill for. Phones store the filming location there. PyAV's wheels bundle
     FFmpeg, so neither CI nor the slim image needs a system package.
   - **Storage:** files are named `<uuid4>.<ext>` behind a `MediaStore` protocol: a local
     directory in development, a private GCS bucket in production. Stores accept only keys of
     that shape, so a stored URI can't point anywhere else.
   - **Reading:** the owner gets a signed URL valid for 15 minutes from
     `GET /v1/attachments/{id}`. Locally this is `/v1/media/{token}`, an itsdangerous token with
     its own salt, so it can't be swapped for a session cookie. Like a GCS V4 URL, the token alone
     grants access, so an `<img src>` works across origins without the cookie.
   - **Limits:** uploads have their own per-user rate limit.
2. **Sending claims the attachments, all or nothing.**
   - Each attachment must be the user's, ready and unsent, and a message may carry at most one
     video. Otherwise the reply is a single `invalid_attachment` SSE error (422).
   - The claim binds the attachments to the conversation inside the request's transaction, with
     row locks. The turn binds them to the user message (`message_id IS NULL`), so an attachment
     is sent once.
   - A turn refused after the claim (busy, rate limited) leaves them claimed by that
     conversation, where they can be sent again.
3. **A `perceive` node runs before `understand`.**
   - It loads the message's attachments through a `MediaSource`, which checks ownership again.
     All photos go to the `vision` task in one call; a video goes to Gemini at the same time.
   - Results are cached on the attachment, so a turn that is rolled back and retried doesn't pay
     twice.
   - Checkpoints hold only the analyses, never image bytes.
   - The media component writes `attachments.analysis` itself, as the MCP servers write their
     tables; the agent still writes only its checkpointer.
4. **Photos become unconfirmed slots through a pure mapping.**
   - `engine/perception.py` turns the results into `PerceivedSlot`s with the model's confidence;
     `TurnInput.media` carries them into `transition()`. They are stored as
     `source="vision"`/`"video"` and `confirmed=False`. Below `LOW_CONFIDENCE` (now 0.7, as in
     the spec) the `confirm_appliance` step shows an `ApplianceConfirmCard`.
   - **Precedence:**
     - Words beat the photo.
     - A photo never overwrites what the user said, but replaces a profile prefill, which then
       unlinks.
     - A newer photo beats an older one.
     - A photo of another appliance than the one the user means adds nothing, and never switches
       the issue.
     - A photo of another brand doesn't lend its model number.
     - Where a journey has no confirm step, low-confidence values are dropped.
     - A value the user confirmed on the card counts as theirs from then on.
   - **The confirm step answers the card the user saw.** A yes or no applies only to the values
     the card showed, unchanged. Values from a photo sent with the answer ("No, here's the right
     sticker") get their own question, and `user_confirmed` needs nothing left unconfirmed.
   - **Confidence is about identity.** The model's confidence covers category, brand and model
     number. An error code or visible issue from a photo the model understood (at least 0.3) is
     not held back for confirmation by an unreadable nameplate.
   - With nothing running, a photo of an appliance starts `troubleshoot`.
   - Hazards seen in media escalate like typed ones (`HazardHit.source="media"`).
   - A failed or timed-out analysis gives M-MEDIA-01, a fixed "please describe it in words". It
     is the whole reply only when the message has nothing else; otherwise it comes before the
     reply.
5. **Video is analyzed inside the turn, within the `video` task's 60 s.**
   - The "analyzing" status is streamed first; the SSE heartbeat keeps the stream open.
   - Analyzing at upload time was rejected:
     - Cloud Run throttles CPU after a response is sent.
     - Clips the user never sends would be paid for.
     - It would need job state and polling.
   - Gemini is called with the official `google-genai` SDK, because LiteLLM has no Files API
     flow (upload, wait for processing, refer). The uploaded file is deleted in `finally`, and
     usage goes to `record_usage()` for the spend cap.
   - Without `GEMINI_API_KEY`, videos degrade to M-MEDIA-01 at once.
6. **Image text is data.**
   - The vision prompt tells the model to transcribe instructions, not follow them, and string
     fields are length-capped.
   - `nameplate_text` is stored but never put in a prompt. NLU sees only visible issues and the
     displayed code, inside `<media_analysis>`, neutralized like all prompt input.
   - The appliance's identity reaches the journey only as perceived slots, so a photo can't
     become a confirmed `source="user"` value.
7. **Evals use synthetic images plus licensed web photos, none of them in git.**
   - `homehelper_evals.vision` measures per-field accuracy and calibration: how many wrong
     identifications fall below the threshold (caught by the confirm step), how many confident
     answers are wrong, ECE, and a threshold sweep.
   - Synthetic nameplates and error displays for manifest models are rendered from their labels.
     Web photos must be CC0, public domain, CC BY or CC BY-SA, reviewed by a person, and pinned by
     sha256.
   - The `multimodal` conversation suite sends photos with scripted turns, and skips cases whose
     files aren't present.

## Consequences

- The UI and the API never hand out a stored file directly; GCS signing on Cloud Run needs
  `roles/iam.serviceAccountTokenCreator` on the service account (M8).
- **Media is never deleted yet.** Uploads that are never sent, and the media of soft-deleted
  conversations, stay in storage. A GCS lifecycle rule and a local cleanup command are left for
  M8.
- **Videos sit in memory during a turn.** A video (up to 100 MB) is read into memory once per
  turn that analyzes it.
- **A video timeout can strand a remote file.** If the 60 s budget runs out during the upload
  itself, no file name exists yet to delete, and Gemini expires it after 48 hours.
- `pi-heif` and PyAV ship LGPL builds of libheif and FFmpeg as separate shared libraries; they
  are used unmodified.
- Gemini's free tier may use uploads for training; production needs a paid key.
- The baseline agent ignores attachments, so multimodal numbers have no baseline comparison.
