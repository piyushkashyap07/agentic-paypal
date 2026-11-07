import { describe, expect, it } from "vitest";
import { formatMoney } from "./money";

describe("formatMoney", () => {
  it("formats dollars", () => {
    expect(formatMoney("300", "USD")).toBe("$300.00");
  });

  it("treats null as zero and defaults to USD", () => {
    expect(formatMoney(null)).toBe("$0.00");
  });

  it("falls back for an invalid currency code", () => {
    expect(formatMoney(5, "NOPE!")).toBe("5.00 NOPE!");
  });
});
