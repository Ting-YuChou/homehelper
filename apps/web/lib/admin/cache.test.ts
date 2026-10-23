import { describe, expect, it } from "vitest";

import { bumpAnnotations, isReviewListKey, isSampleKey } from "./cache";

const page = (ids: [string, number][], next: string | null = null) => ({
  items: ids.map(([id, annotation_count]) => ({ id, annotation_count })),
  next_before: next,
});

describe("review list cache", () => {
  it("tells list queries and samples apart", () => {
    expect(isReviewListKey(["admin", "conversations", { limit: 50 }])).toBe(true);
    expect(isReviewListKey(["admin", "conversation", "c1"])).toBe(false);
    expect(isSampleKey(["admin", "conversations", { sample: 20 }])).toBe(true);
    expect(isSampleKey(["admin", "conversations", { limit: 50 }])).toBe(false);
  });

  it("counts an annotation on the conversation's row only", () => {
    const data = {
      pages: [
        page(
          [
            ["c1", 0],
            ["c2", 1],
          ],
          "x",
        ),
        page([["c3", 2]]),
      ],
      pageParams: [null, "x"],
    };
    const bumped = bumpAnnotations(data, "c2", -1);
    expect(bumped?.pages.flatMap((p) => p.items.map((i) => i.annotation_count))).toEqual([0, 0, 2]);
    expect(data.pages[0].items[1].annotation_count).toBe(1); // not mutated
    expect(bumpAnnotations(undefined, "c1", 1)).toBeUndefined();
  });
});
