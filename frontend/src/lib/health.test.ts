import { describe, expect, it } from "vitest";
import { fixtures } from "../test/fixtures";
import { freshHealth } from "../test/mocks/fixtures";
import { effectiveStatus } from "./health";

describe("effectiveStatus", () => {
  const generated = Date.parse(fixtures.health.generated_at);

  it("trusts the published status while the health file is fresh", () => {
    expect(effectiveStatus(fixtures.health, new Date(generated + 5 * 60_000))).toBe("ok");
    expect(
      effectiveStatus({ ...fixtures.health, status: "degraded" }, new Date(generated + 60_000)),
    ).toBe("degraded");
  });

  it("reports stale when the health file itself stopped updating (> 15 min)", () => {
    expect(effectiveStatus(fixtures.health, new Date(generated + 16 * 60_000))).toBe("stale");
  });

  it("passes stale and unknown through", () => {
    expect(effectiveStatus({ ...fixtures.health, status: "stale" }, new Date(generated))).toBe(
      "stale",
    );
    expect(effectiveStatus({ ...fixtures.health, status: "unknown" }, new Date(generated))).toBe(
      "unknown",
    );
  });

  it("mock helper shifts every timestamp so the file looks fresh", () => {
    const now = new Date("2030-01-01T12:00:00Z");
    const h = freshHealth(fixtures.health, now);
    expect(h.generated_at).toBe("2030-01-01T11:59:00.000Z");
    expect(effectiveStatus(h, now)).toBe("ok");
    expect(Date.parse(h.recent_gaps[0]!.end) - Date.parse(h.recent_gaps[0]!.start)).toBe(
      8 * 60_000,
    );
  });
});
