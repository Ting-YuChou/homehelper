import { describe, expect, it } from "vitest";

import { loginMessage } from "./login";

describe("loginMessage", () => {
  it("names a wrong access code only when one is required", () => {
    expect(loginMessage(403, true)).toBe("That access code isn't right.");
    expect(loginMessage(403, false)).toBe("Couldn't sign in. Is the API running?");
  });

  it("explains the rate limit", () => {
    expect(loginMessage(429, true)).toBe("Too many sign-ins. Try again in an hour.");
  });
});
