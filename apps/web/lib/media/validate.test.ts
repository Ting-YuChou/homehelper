import { describe, expect, it } from "vitest";

import { checkFiles, kindOf, MAX_ATTACHMENTS } from "./validate";

function file(name: string, type: string, size = 1000): File {
  const blob = new File([new Uint8Array(Math.min(size, 16))], name, { type });
  Object.defineProperty(blob, "size", { value: size });
  return blob;
}

describe("kindOf", () => {
  it("knows the photo and video types the API accepts", () => {
    expect(kindOf(file("a.jpg", "image/jpeg"))).toBe("image");
    expect(kindOf(file("a.heic", "image/heic"))).toBe("image");
    expect(kindOf(file("a.HEIC", ""))).toBe("image"); // Safari sometimes sends no type
    expect(kindOf(file("a.mov", "video/quicktime"))).toBe("video");
    expect(kindOf(file("a.gif", "image/gif"))).toBeNull();
    expect(kindOf(file("a.pdf", "application/pdf"))).toBeNull();
  });
});

describe("checkFiles", () => {
  it("accepts photos and one video", () => {
    const result = checkFiles([], [file("a.jpg", "image/jpeg"), file("b.mp4", "video/mp4")]);
    expect(result.accepted.map((f) => f.name)).toEqual(["a.jpg", "b.mp4"]);
    expect(result.errors).toEqual([]);
  });

  it("refuses other types and oversized files", () => {
    const result = checkFiles(
      [],
      [
        file("doc.pdf", "application/pdf"),
        file("big.jpg", "image/jpeg", 11 * 1024 * 1024),
        file("long.mp4", "video/mp4", 101 * 1024 * 1024),
      ],
    );
    expect(result.accepted).toEqual([]);
    expect(result.errors).toEqual([
      "doc.pdf: send a photo (JPEG, PNG, WebP, HEIC) or a video (MP4, MOV, WebM).",
      "big.jpg: photos can be up to 10 MB.",
      "long.mp4: videos can be up to 100 MB.",
    ]);
  });

  it("keeps to four attachments and one video per message", () => {
    const already = [{ kind: "video" as const }, { kind: "image" as const }];
    const result = checkFiles(already, [
      file("c.mp4", "video/mp4"),
      file("d.png", "image/png"),
      file("e.png", "image/png"),
      file("f.png", "image/png"),
    ]);
    expect(result.accepted.map((f) => f.name)).toEqual(["d.png", "e.png"]);
    expect(result.errors).toEqual([
      "c.mp4: one video per message.",
      `f.png: up to ${MAX_ATTACHMENTS} attachments per message.`,
    ]);
  });
});
