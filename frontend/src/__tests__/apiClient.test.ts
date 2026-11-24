import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClientError, fetchHealth, fetchProfiles } from "../api/client";

describe("API client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches health payload successfully", async () => {
    const mockHealth = {
      status: "ok",
      app_name: "SONORA",
      version: "0.1.0-stage1",
    };

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockHealth,
      }),
    );

    const data = await fetchHealth();
    expect(data.app_name).toBe("SONORA");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/health",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("parses structured backend error envelopes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({
          error: {
            code: "RESOURCE_NOT_FOUND",
            message: "Profile not found",
            details: { id: "missing" },
          },
        }),
      }),
    );

    await expect(fetchProfiles()).rejects.toMatchObject({
      name: "ApiClientError",
      code: "RESOURCE_NOT_FOUND",
      message: "Profile not found",
      status: 404,
    } satisfies Partial<ApiClientError>);
  });
});
