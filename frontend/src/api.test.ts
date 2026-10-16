// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, editable, original } from "./api";
afterEach(() => vi.unstubAllGlobals());
describe("same-origin financial API client", () => {
  it("uses the deployment prefix and explicit write header", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response('{"ok":true}', {
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    await api("/transactions", "POST", { values: { amount: 0 } });
    expect(fetch.mock.calls[0][0]).toBe("/steuer/api/transactions");
    const init = fetch.mock.calls[0][1];
    expect(init.headers["X-KESt-Request"]).toBe("1");
    expect(JSON.parse(init.body).values.amount).toBe(0);
  });
  it("keeps upload multipart boundaries under browser control", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetch);
    await api("/import", "POST", new FormData());
    expect(fetch.mock.calls[0][1].headers["Content-Type"]).toBeUndefined();
  });
  it("shows server validation instead of reporting success", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response('{"detail":"Begründung fehlt"}', { status: 422 }),
        ),
    );
    await expect(api("/transactions/1", "PATCH", {})).rejects.toThrow(
      "Begründung fehlt",
    );
  });
  it("reports offline writes as failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(api("/transactions", "POST", {})).rejects.toThrow(
      "Eingaben bleiben im Formular",
    );
  });
  it("filters immutable metadata and preserves empty vs zero", () => {
    const schema = { properties: { amount: {}, notes: {} } };
    expect(
      editable(schema, { id: 1, amount: 0, notes: null, deleted: 1 }),
    ).toEqual({ amount: 0, notes: null });
    expect(original(3)).toBe("/steuer/api/documents/3/original");
  });
  it("rejects invalid successful JSON instead of passing an error object to tables", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("broken JSON")),
    );
    await expect(api("/exports?year=2024")).rejects.toThrow(
      "Ungültige Serverantwort",
    );
  });
  it("preserves cancellation while the response body is being read", async () => {
    const aborted = new DOMException("cancelled", "AbortError");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({
          ok: true,
          status: 200,
          json: () => Promise.reject(aborted),
        }),
    );
    await expect(api("/exports?year=2024")).rejects.toBe(aborted);
  });
});
