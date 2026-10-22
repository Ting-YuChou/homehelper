// Client-side checks before an upload (spec §11.1). The API checks the real bytes again; these
// only spare the user an upload that would be refused.
export type MediaKind = "image" | "video";

export const MAX_ATTACHMENTS = 4;
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
export const MAX_VIDEO_BYTES = 100 * 1024 * 1024;
export const ACCEPT =
  "image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif,video/mp4,video/quicktime,video/webm";

const IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"]);
const VIDEO_TYPES = new Set(["video/mp4", "video/quicktime", "video/webm"]);
const IMAGE_EXTENSIONS = /\.(jpe?g|png|webp|heic|heif)$/i;
const VIDEO_EXTENSIONS = /\.(mp4|mov|webm)$/i;

export function kindOf(file: File): MediaKind | null {
  if (IMAGE_TYPES.has(file.type)) return "image";
  if (VIDEO_TYPES.has(file.type)) return "video";
  if (file.type) return null;
  // Some browsers report no type for HEIC; fall back to the name (the API decides anyway).
  if (IMAGE_EXTENSIONS.test(file.name)) return "image";
  if (VIDEO_EXTENSIONS.test(file.name)) return "video";
  return null;
}

export function checkFiles(
  current: { kind: MediaKind }[],
  files: File[],
): { accepted: File[]; errors: string[] } {
  const accepted: File[] = [];
  const errors: string[] = [];
  let count = current.length;
  let videos = current.filter((item) => item.kind === "video").length;
  for (const file of files) {
    const kind = kindOf(file);
    if (kind === null) {
      errors.push(`${file.name}: send a photo (JPEG, PNG, WebP, HEIC) or a video (MP4, MOV, WebM).`);
    } else if (kind === "image" && file.size > MAX_IMAGE_BYTES) {
      errors.push(`${file.name}: photos can be up to 10 MB.`);
    } else if (kind === "video" && file.size > MAX_VIDEO_BYTES) {
      errors.push(`${file.name}: videos can be up to 100 MB.`);
    } else if (kind === "video" && videos >= 1) {
      errors.push(`${file.name}: one video per message.`);
    } else if (count >= MAX_ATTACHMENTS) {
      errors.push(`${file.name}: up to ${MAX_ATTACHMENTS} attachments per message.`);
    } else {
      accepted.push(file);
      count += 1;
      if (kind === "video") videos += 1;
    }
  }
  return { accepted, errors };
}
