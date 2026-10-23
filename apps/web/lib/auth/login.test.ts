import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/client";

import { isWrongCode, loginMessage, WRONG_CODE } from "./login";

describe("loginMessage", () => {
  it("names a wrong access code", () => {
    const error = new ApiError(403, WRONG_CODE);
    expect(isWrongCode(error)).toBe(true);
    expect(loginMessage(error)).toBe("That access code isn't right.");
  });

  it("doesn't blame the code for another 403", () => {
    const error = new ApiError(403, "Origin not allowed");
    expect(isWrongCode(error)).toBe(false);
    expect(loginMessage(error)).toBe("Couldn't sign in. Is the API running?");
  });

  it("explains the rate limit", () => {
    expect(loginMessage(new ApiError(429, "Too many"))).toBe(
      "Too many sign-ins. Try again in an hour.",
    );
  });
});
