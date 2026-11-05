import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    json: async () => body,
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("posts chat messages with the thread id", async () => {
    const fetchMock = mockFetch(200, { message: "hi", thread_id: "t1", status: "ok" });
    await api.chat("hello", "t1");
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/chat");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ message: "hello", thread_id: "t1" });
  });

  it("routes simulate-overdue to the demo endpoint", async () => {
    const fetchMock = mockFetch(200, {});
    await api.invoiceAction("INV2-1", "simulate-overdue");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/demo/invoices/INV2-1/simulate-overdue");
  });

  it("sends an empty body for refunds", async () => {
    const fetchMock = mockFetch(200, {});
    await api.invoiceAction("INV2-1", "refund");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/invoices/INV2-1/refund");
    expect(fetchMock.mock.calls[0][1].body).toBe("{}");
  });

  it("surfaces the backend's error detail", async () => {
    mockFetch(502, { detail: "PayPal rejected it" });
    await expect(api.listInvoices()).rejects.toThrow("PayPal rejected it");
  });

  it("falls back to a generic error when the body isn't JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => { throw new Error("x"); } }));
    await expect(api.listEvents()).rejects.toThrow("Is the backend running?");
  });
});
