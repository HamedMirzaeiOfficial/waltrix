import { describe, expect, it, vi } from "vitest";

import {
  Waltrix,
  WaltrixApiError,
  WaltrixNetworkError,
  WaltrixUnknownOutcomeError,
  formatMoney,
  paginate,
  parseMoney,
} from "../src/index.js";

const TX = { id: "t1", status: "posted", amount: 100, currency: "USD" };
const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });

function client(fetchImpl: typeof fetch, extra: Partial<ConstructorParameters<typeof Waltrix>[0]> = {}) {
  const c = new Waltrix({ apiKey: "wtx_key_test", baseUrl: "http://api.test", fetch: fetchImpl, ...extra });
  c.sleep = async () => {};
  return c;
}

describe("retries and idempotency", () => {
  it("reuses one idempotency key across retries", async () => {
    const keys: string[] = [];
    const f = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      keys.push(new Headers(init?.headers).get("Idempotency-Key")!);
      if (keys.length < 3) throw new TypeError("fetch failed");
      return json(201, TX);
    });
    const tx = await client(f as typeof fetch).transfers.create({
      source_wallet_id: "a",
      destination_wallet_id: "b",
      amount: 100,
      currency: "USD",
    });
    expect(tx.id).toBe("t1");
    expect(keys).toHaveLength(3);
    expect(new Set(keys).size).toBe(1);
  });

  it("sends a caller-provided key and auth header", async () => {
    const f = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      const h = new Headers(init?.headers);
      expect(String(url)).toBe("http://api.test/api/v1/transfers");
      expect(h.get("Idempotency-Key")).toBe("order-1");
      expect(h.get("Authorization")).toBe("Bearer wtx_key_test");
      return json(201, TX);
    });
    await client(f as typeof fetch).transfers.create(
      { source_wallet_id: "a", destination_wallet_id: "b", amount: 100, currency: "USD" },
      { idempotencyKey: "order-1" },
    );
  });

  it("throws UnknownOutcome with the key when a mutation never gets an answer", async () => {
    const f = vi.fn(async () => {
      throw new TypeError("network down");
    });
    const err = await client(f as typeof fetch, { maxRetries: 2 })
      .holds.release("h1", { idempotencyKey: "k-9" })
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(WaltrixUnknownOutcomeError);
    expect((err as WaltrixUnknownOutcomeError).idempotencyKey).toBe("k-9");
    expect(f).toHaveBeenCalledTimes(3);
  });

  it("treats a caller abort of a mutation as unknown outcome, not failure", async () => {
    const controller = new AbortController();
    const f = vi.fn(
      (_u: string | URL | Request, init?: RequestInit) =>
        new Promise<Response>((_, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
          controller.abort();
        }),
    );
    const err = await client(f as typeof fetch)
      .transfers.create(
        { source_wallet_id: "a", destination_wallet_id: "b", amount: 1, currency: "USD" },
        { signal: controller.signal },
      )
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(WaltrixUnknownOutcomeError);
    expect((err as WaltrixUnknownOutcomeError).aborted).toBe(true);
  });

  it("never retries a POST without an idempotency key", async () => {
    const f = vi.fn(async () => {
      throw new TypeError("network");
    });
    await expect(client(f as typeof fetch).reconciliation.run()).rejects.toBeInstanceOf(WaltrixUnknownOutcomeError);
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("retries GETs and then raises a network error", async () => {
    const f = vi.fn(async () => {
      throw new TypeError("network");
    });
    await expect(client(f as typeof fetch, { maxRetries: 1 }).wallets.get("w")).rejects.toBeInstanceOf(
      WaltrixNetworkError,
    );
    expect(f).toHaveBeenCalledTimes(2);
  });

  it("retries 409 concurrent_request and honors Retry-After", async () => {
    const delays: number[] = [];
    const responses = [
      json(409, { error: { code: "concurrent_request", message: "busy" } }),
      json(429, { error: { code: "rate_limited", message: "slow" } }, { "retry-after": "2" }),
      json(201, TX),
    ];
    const c = client((async () => responses.shift()!) as typeof fetch);
    c.sleep = async (ms) => {
      delays.push(ms);
    };
    await c.transfers.create({ source_wallet_id: "a", destination_wallet_id: "b", amount: 1, currency: "USD" });
    expect(delays[1]).toBe(2000);
  });
});

describe("errors and validation", () => {
  it("maps business failures with the failed transaction id", async () => {
    const f = async () =>
      json(422, {
        error: { code: "insufficient_funds", message: "no", details: { transaction_id: "t-f" }, correlation_id: "c1" },
      });
    const err = (await client(f as typeof fetch)
      .transfers.create({ source_wallet_id: "a", destination_wallet_id: "b", amount: 1, currency: "USD" })
      .catch((e: unknown) => e)) as WaltrixApiError;
    expect(err).toBeInstanceOf(WaltrixApiError);
    expect(err.isBusinessFailure).toBe(true);
    expect(err.transactionId).toBe("t-f");
    expect(err.correlationId).toBe("c1");
  });

  it("validation errors are not business failures", async () => {
    const f = async () => json(422, { error: { code: "validation_failed", message: "bad" } });
    const err = (await client(f as typeof fetch)
      .wallets.list()
      .catch((e: unknown) => e)) as WaltrixApiError;
    expect(err.isBusinessFailure).toBe(false);
  });

  it.each([1.5, 0, -1, Number.MAX_SAFE_INTEGER + 1, Number.NaN])("rejects amount %s before sending", (amount) => {
    const f = vi.fn();
    expect(() =>
      client(f as unknown as typeof fetch).transfers.create({
        source_wallet_id: "a",
        destination_wallet_id: "b",
        amount,
        currency: "USD",
      }),
    ).toThrow(TypeError);
    expect(f).not.toHaveBeenCalled();
  });

  it("refuses path traversal in ids", () => {
    expect(() => client(vi.fn() as unknown as typeof fetch).wallets.get("../api-keys")).toThrow(TypeError);
  });

  it("session mode sends CSRF header, org header and credentials", async () => {
    const f = vi.fn(async (_u: string | URL | Request, init?: RequestInit) => {
      const h = new Headers(init?.headers);
      expect(h.get("X-Requested-With")).toBe("waltrix-web");
      expect(h.get("X-Waltrix-Organization")).toBe("org-1");
      expect(h.get("Authorization")).toBeNull();
      expect(init?.credentials).toBe("include");
      return json(200, { data: [], next_cursor: null, has_more: false });
    });
    const c = new Waltrix({ fetch: f as typeof fetch, session: { organizationId: () => "org-1" } });
    await c.wallets.list();
  });
});

describe("pagination and money", () => {
  it("follows cursors", async () => {
    const pages: Record<string, unknown> = {
      "": { data: [1, 2], next_cursor: "c2", has_more: true },
      c2: { data: [3], next_cursor: null, has_more: false },
    };
    const c = client((async (url: string | URL | Request) =>
      json(200, pages[new URL(String(url)).searchParams.get("cursor") ?? ""])) as typeof fetch);
    const out: unknown[] = [];
    for await (const item of paginate((cursor) => c.wallets.list({ limit: 2, cursor }))) out.push(item);
    expect(out).toEqual([1, 2, 3]);
  });

  it.each([
    ["12.5", "USD", 1250],
    ["0.01", "USD", 1],
    ["1,234.56", "USD", 123456],
    ["500", "JPY", 500],
    ["0.1", "USD", 10],
    ["9007199254740.99", "USD", 900719925474099],
  ])("parseMoney(%s %s) = %s", (input, cur, expected) => {
    expect(parseMoney(input, cur)).toBe(expected);
  });

  it.each([
    ["1.234", "USD"],
    ["-5", "USD"],
    ["1.5", "JPY"],
    ["abc", "USD"],
    ["", "USD"],
    ["1e5", "USD"],
  ])("parseMoney rejects %s %s", (input, cur) => {
    expect(parseMoney(input, cur)).toBeNull();
  });

  it("formats from integers without float drift", () => {
    expect(formatMoney(123456, "USD")).toBe("$1,234.56");
    expect(formatMoney(5, "USD")).toBe("$0.05");
    expect(formatMoney(500, "JPY")).toBe("¥500");
    expect(formatMoney(900719925474099, "USD")).toBe("$9,007,199,254,740.99");
  });
});
