import { describe, expect, it } from "vitest";

import { signInMessage } from "./session";

describe("admin sign-in messages", () => {
  it.each([
    [401, "That admin token isn't right."],
    [429, "Too many attempts. Try again in an hour."],
    [403, "This page isn't allowed to sign in to the API."],
    [500, "Can't reach the HomeHelper API right now."],
  ])("explains %i", (status, message) => {
    expect(signInMessage(status)).toBe(message);
  });
});
