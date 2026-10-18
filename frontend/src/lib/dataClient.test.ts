import { afterEach, describe, expect, it, vi } from "vitest";
import { agency, fixtures } from "../test/fixtures";
import { FIXTURE_FILES } from "../test/mocks/fixtures";
import {
  DataError,
  fetchManifest,
  fetchValidation,
  findAgency,
  routeDetailPath,
} from "./dataClient";

afterEach(() => vi.unstubAllGlobals());

describe("routeDetailPath", () => {
  it("substitutes the URL-encoded route id into the template", () => {
    expect(routeDetailPath(agency, "1")).toBe(
      `/data/v1/builds/${fixtures.manifest.build_id}/mbta/routes/1.json`,
    );
    expect(routeDetailPath(agency, "CR-Fitchburg/A b")).toMatch(
      /routes\/CR-Fitchburg%2FA%20b\.json$/,
    );
  });
});

describe("fixtures match the manifest", () => {
  it("every manifest path has a fixture", () => {
    const paths = [
      agency.paths.stops,
      agency.paths.routes,
      agency.paths.coverage,
      agency.paths.health,
      agency.paths.validation!,
    ];
    for (const p of paths) expect(FIXTURE_FILES[p], p).toBeDefined();
    expect(FIXTURE_FILES[routeDetailPath(agency, "Red")]).toBe("mbta-route-Red.json");
    expect(findAgency(fixtures.manifest, "mbta")?.name).toBe("MBTA");
    expect(findAgency(fixtures.manifest, "septa")).toBeNull();
  });
});

describe("fetch helpers", () => {
  it("rejects an unsupported manifest schema version", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(new Response(JSON.stringify({ schema_version: 2, agencies: [] }))),
      ),
    );
    await expect(fetchManifest()).rejects.toThrow(/schema version 2/);
  });

  it("treats a missing validation report as absent, not as an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("", { status: 404 }))),
    );
    await expect(fetchValidation(agency)).resolves.toBeNull();
    await expect(
      fetchValidation({ ...agency, paths: { ...agency.paths, validation: null } }),
    ).resolves.toBeNull();
  });

  it("surfaces other HTTP errors as DataError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("", { status: 503 }))),
    );
    await expect(fetchManifest()).rejects.toBeInstanceOf(DataError);
  });
});
