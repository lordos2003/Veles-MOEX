/**
 * P1 (MVP-7.3): a request with a JSON body must carry
 * Content-Type: application/json. Without it the browser ships text/plain,
 * and recent FastAPI versions reject the body as a string — the sandbox
 * pay-in error `model_attributes_type ... "input":"{\"account_id\":...}"`.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";

type FetchCall = [input: RequestInfo | URL, init?: RequestInit | undefined];

function stubFetchOk(): () => FetchCall[] {
  const calls: FetchCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push([input, init]);
      return {
        ok: true,
        status: 200,
        text: async () => "{}",
      } as Response;
    }),
  );
  return () => calls;
}

function headersOf(call: FetchCall): Record<string, string> {
  return (call[1]?.headers ?? {}) as Record<string, string>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api: Content-Type header (P1)", () => {
  it("post with body sends Content-Type: application/json", async () => {
    const calls = stubFetchOk();
    await api.post("/api/test", { a: 1 });
    expect(headersOf(calls()[0])["Content-Type"]).toBe("application/json");
  });

  it("put with body sends Content-Type: application/json", async () => {
    const calls = stubFetchOk();
    await api.put("/api/test", { a: 1 });
    expect(headersOf(calls()[0])["Content-Type"]).toBe("application/json");
  });

  it("patch with body sends Content-Type: application/json", async () => {
    const calls = stubFetchOk();
    await api.patch("/api/test", { a: 1 });
    expect(headersOf(calls()[0])["Content-Type"]).toBe("application/json");
  });

  it("get sends no Content-Type header", async () => {
    const calls = stubFetchOk();
    await api.get("/api/test");
    expect(headersOf(calls()[0])["Content-Type"]).toBeUndefined();
  });

  it("post without body sends no Content-Type header", async () => {
    const calls = stubFetchOk();
    await api.post("/api/test");
    expect(headersOf(calls()[0])["Content-Type"]).toBeUndefined();
  });
});
