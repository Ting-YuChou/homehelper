import { describe, expect, it } from "vitest";

import { safeNext } from "./safe-next";

const ORIGIN = "http://localhost:3000";

describe("safeNext", () => {
  it("keeps paths on this site", () => {
    expect(safeNext("/chat/conv_1", ORIGIN)).toBe("/chat/conv_1");
    expect(safeNext("/chat?x=1", ORIGIN)).toBe("/chat?x=1");
    expect(safeNext(null, ORIGIN)).toBe("/chat");
  });

  it.each(["//evil.com", "/\\evil.com", "/\t/evil.com", "https://evil.com/chat", "javascript:alert(1)"])(
    "refuses %j",
    (next) => {
      expect(safeNext(next, ORIGIN)).toBe("/chat");
    },
  );
});
