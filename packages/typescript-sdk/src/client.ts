/**
 * Waltrix TypeScript client.
 *
 * - Works in browsers and Node 18+ (global `fetch`, `AbortController`, `crypto`).
 * - Two auth modes: `apiKey` (servers) or cookie `session` mode (the dashboard).
 * - Every money-moving method sends an `Idempotency-Key`. Pass your own
 *   (`{ idempotencyKey }`) to make retries across process restarts or UI
 *   re-submissions safe; otherwise one is generated per call and reused for
 *   that call's automatic retries.
 * - Retries only retry-safe requests (GET, or POST with an idempotency key) on
 *   network errors, timeouts, 429, 502/503/504 and 409 `concurrent_request`.
 * - A mutation without a definitive answer throws `WaltrixUnknownOutcomeError`.
 */

import { WaltrixApiError, WaltrixNetworkError, WaltrixUnknownOutcomeError, errorFromResponse } from "./errors.js";
import type * as T from "./types.js";

export interface WaltrixOptions {
  /** Origin of the API, e.g. "https://ledger.example.com". Empty string = same origin. */
  baseUrl?: string;
  /** Server-side API key (`wtx_key_...`). Never ship it to browsers. */
  apiKey?: string;
  /** Cookie-session mode for first-party browser apps. */
  session?: {
    /** Organization to act in; verified server-side against the user's membership. */
    organizationId?: () => string | null | undefined;
  };
  fetch?: typeof fetch;
  timeoutMs?: number;
  maxRetries?: number;
  backoffBaseMs?: number;
  backoffMaxMs?: number;
  headers?: Record<string, string>;
}

export interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

export interface MutationOptions extends RequestOptions {
  /** Reuse the same key when retrying the same logical operation. */
  idempotencyKey?: string;
}

interface Spec {
  method: "GET" | "POST" | "PATCH" | "DELETE";
  path: string;
  body?: unknown;
  query?: object;
  idempotencyKey?: string;
}

const RETRY_STATUSES = new Set([429, 502, 503, 504]);
export const MAX_SAFE_AMOUNT = Number.MAX_SAFE_INTEGER;

export function newIdempotencyKey(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  const bytes = new Uint8Array(16);
  c.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function assertAmount(amount: unknown, field = "amount"): asserts amount is number {
  if (typeof amount !== "number" || !Number.isSafeInteger(amount) || amount <= 0) {
    throw new TypeError(`${field} must be a positive integer number of minor units`);
  }
}

function seg(id: string): string {
  if (!id || id.includes("/")) throw new TypeError("invalid identifier");
  return encodeURIComponent(id);
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason);
    const t = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        reject(signal.reason);
      },
      { once: true },
    );
  });
}

export class Waltrix {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly backoffBaseMs: number;
  private readonly backoffMaxMs: number;
  private readonly headers: Record<string, string>;
  /** Injection point for tests. */
  sleep: (ms: number, signal?: AbortSignal) => Promise<void> = sleep;

  constructor(private readonly options: WaltrixOptions = {}) {
    if (options.apiKey && options.session) throw new TypeError("use either apiKey or session, not both");
    if (options.apiKey && !options.apiKey.startsWith("wtx_key_"))
      throw new TypeError("apiKey must start with wtx_key_");
    this.baseUrl = (options.baseUrl ?? "").replace(/\/$/, "") + "/api/v1";
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? 15_000;
    this.maxRetries = options.maxRetries ?? 3;
    this.backoffBaseMs = options.backoffBaseMs ?? 250;
    this.backoffMaxMs = options.backoffMaxMs ?? 4_000;
    this.headers = { Accept: "application/json", ...options.headers };
    if (options.apiKey) this.headers["Authorization"] = `Bearer ${options.apiKey}`;
    if (options.session) this.headers["X-Requested-With"] = "waltrix-web";
  }

  // --- transport -----------------------------------------------------------------

  private url(spec: Spec): string {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(spec.query ?? {})) {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    }
    const q = qs.toString();
    return `${this.baseUrl}${spec.path}${q ? `?${q}` : ""}`;
  }

  private delay(attempt: number, res: Response | null): number {
    const ra = res?.headers.get("retry-after");
    if (ra && !Number.isNaN(Number(ra))) return Math.min(Number(ra) * 1000, this.backoffMaxMs * 4);
    const cap = Math.min(this.backoffMaxMs, this.backoffBaseMs * 2 ** attempt);
    return Math.random() * cap;
  }

  private async retryable(res: Response): Promise<boolean> {
    if (RETRY_STATUSES.has(res.status)) return true;
    if (res.status === 409) {
      const body = (await res
        .clone()
        .json()
        .catch(() => null)) as { error?: { code?: string } } | null;
      return body?.error?.code === "concurrent_request";
    }
    return false;
  }

  private async send<R>(spec: Spec, opts: RequestOptions = {}): Promise<R> {
    const retrySafe = spec.method === "GET" || spec.idempotencyKey !== undefined;
    const attempts = retrySafe ? this.maxRetries + 1 : 1;
    const headers: Record<string, string> = { ...this.headers };
    if (spec.body !== undefined) headers["Content-Type"] = "application/json";
    if (spec.idempotencyKey) headers["Idempotency-Key"] = spec.idempotencyKey;
    const org = this.options.session?.organizationId?.();
    if (org) headers["X-Waltrix-Organization"] = org;

    let lastError: unknown = null;
    let lastResponse: Response | null = null;
    for (let attempt = 0; attempt < attempts; attempt++) {
      const controller = new AbortController();
      const timeout = setTimeout(
        () => controller.abort(new DOMException("timeout", "TimeoutError")),
        opts.timeoutMs ?? this.timeoutMs,
      );
      const onAbort = () => controller.abort(opts.signal?.reason);
      opts.signal?.addEventListener("abort", onAbort, { once: true });
      try {
        if (opts.signal?.aborted) throw opts.signal.reason;
        const res = await this.fetchImpl(this.url(spec), {
          method: spec.method,
          headers,
          body: spec.body === undefined ? undefined : JSON.stringify(spec.body),
          signal: controller.signal,
          credentials: this.options.session ? "include" : "same-origin",
        });
        if (!(await this.retryable(res))) return await this.parse<R>(res);
        lastResponse = res;
        lastError = null;
      } catch (err) {
        if (err instanceof WaltrixApiError) throw err;
        if (opts.signal?.aborted) {
          // The caller cancelled. For reads that is simply a cancellation; for writes we
          // cannot know whether the server already applied the request.
          if (spec.method === "GET") throw opts.signal.reason;
          throw new WaltrixUnknownOutcomeError("request aborted; outcome unknown", spec.idempotencyKey ?? null, true, {
            cause: err,
          });
        }
        lastError = err;
        lastResponse = null;
      } finally {
        clearTimeout(timeout);
        opts.signal?.removeEventListener("abort", onAbort);
      }
      if (attempt + 1 < attempts) await this.sleep(this.delay(attempt, lastResponse), opts.signal);
    }
    if (lastResponse && !(spec.method !== "GET" && lastResponse.status >= 500)) return this.parse<R>(lastResponse);
    if (spec.method === "GET") throw new WaltrixNetworkError("could not reach the Waltrix API", { cause: lastError });
    throw new WaltrixUnknownOutcomeError(
      "no definitive answer from the server; the operation may or may not have been applied",
      spec.idempotencyKey ?? null,
      false,
      { cause: lastError ?? lastResponse?.status },
    );
  }

  private async parse<R>(res: Response): Promise<R> {
    if (res.status === 204) return undefined as R;
    const body: unknown = await res.json().catch(() => null);
    if (res.ok) return body as R;
    throw errorFromResponse(res.status, body);
  }

  private mutate<R>(spec: Omit<Spec, "idempotencyKey">, opts: MutationOptions = {}): Promise<R> {
    return this.send<R>({ ...spec, idempotencyKey: opts.idempotencyKey ?? newIdempotencyKey() }, opts);
  }

  // --- resources -------------------------------------------------------------------

  readonly auth = {
    register: (input: { email: string; password: string; display_name?: string }, o?: RequestOptions) =>
      this.send<T.User>({ method: "POST", path: "/auth/register", body: input }, o),
    login: (input: { email: string; password: string }, o?: RequestOptions) =>
      this.send<T.Me>({ method: "POST", path: "/auth/login", body: input }, o),
    logout: (o?: RequestOptions) => this.send<void>({ method: "POST", path: "/auth/logout", body: {} }, o),
    me: (o?: RequestOptions) => this.send<T.Me>({ method: "GET", path: "/auth/me" }, o),
  };

  readonly organizations = {
    list: (o?: RequestOptions) => this.send<T.Membership[]>({ method: "GET", path: "/organizations" }, o),
    create: (input: { name: string }, o?: RequestOptions) =>
      this.send<T.Organization>({ method: "POST", path: "/organizations", body: input }, o),
    current: (o?: RequestOptions) =>
      this.send<T.CurrentOrganization>({ method: "GET", path: "/organizations/current" }, o),
    update: (input: { name: string }, o?: RequestOptions) =>
      this.send<T.Organization>({ method: "PATCH", path: "/organizations/current", body: input }, o),
  };

  readonly members = {
    list: (o?: RequestOptions) => this.send<T.Member[]>({ method: "GET", path: "/organizations/current/members" }, o),
    add: (input: { email: string; role: T.Role }, o?: RequestOptions) =>
      this.send<T.Member>({ method: "POST", path: "/organizations/current/members", body: input }, o),
    updateRole: (id: string, role: T.Role, o?: RequestOptions) =>
      this.send<T.Member>({ method: "PATCH", path: `/organizations/current/members/${seg(id)}`, body: { role } }, o),
    remove: (id: string, o?: RequestOptions) =>
      this.send<void>({ method: "DELETE", path: `/organizations/current/members/${seg(id)}` }, o),
  };

  readonly apiKeys = {
    list: (o?: RequestOptions) => this.send<T.ApiKey[]>({ method: "GET", path: "/api-keys" }, o),
    create: (
      input: { name: string; role: "finance_operator" | "auditor" | "viewer"; expires_in_days?: number },
      o?: RequestOptions,
    ) => this.send<T.ApiKeyCreated>({ method: "POST", path: "/api-keys", body: input }, o),
    revoke: (id: string, o?: RequestOptions) =>
      this.send<T.ApiKey>({ method: "POST", path: `/api-keys/${seg(id)}/revoke`, body: {} }, o),
    rotate: (id: string, graceHours = 0, o?: RequestOptions) =>
      this.send<T.ApiKeyCreated>(
        { method: "POST", path: `/api-keys/${seg(id)}/rotate`, body: { grace_hours: graceHours } },
        o,
      ),
  };

  readonly wallets = {
    list: (
      params: T.ListParams & { status?: T.WalletStatus; currency?: string; search?: string } = {},
      o?: RequestOptions,
    ) => this.send<T.Page<T.Wallet>>({ method: "GET", path: "/wallets", query: params }, o),
    get: (id: string, o?: RequestOptions) => this.send<T.Wallet>({ method: "GET", path: `/wallets/${seg(id)}` }, o),
    balance: (id: string, o?: RequestOptions) =>
      this.send<T.Balance>({ method: "GET", path: `/wallets/${seg(id)}/balance` }, o),
    create: (input: T.CreateWalletInput, o?: MutationOptions) =>
      this.mutate<T.Wallet>({ method: "POST", path: "/wallets", body: input }, o),
    credit: (id: string, input: T.FundingInput, o?: MutationOptions) => {
      assertAmount(input.amount);
      return this.mutate<T.Transaction>({ method: "POST", path: `/wallets/${seg(id)}/credit`, body: input }, o);
    },
    debit: (id: string, input: T.FundingInput, o?: MutationOptions) => {
      assertAmount(input.amount);
      return this.mutate<T.Transaction>({ method: "POST", path: `/wallets/${seg(id)}/debit`, body: input }, o);
    },
    suspend: (id: string, reason?: string, o?: RequestOptions) =>
      this.send<T.Wallet>({ method: "POST", path: `/wallets/${seg(id)}/suspend`, body: { reason } }, o),
    activate: (id: string, o?: RequestOptions) =>
      this.send<T.Wallet>({ method: "POST", path: `/wallets/${seg(id)}/activate`, body: {} }, o),
    close: (id: string, o?: RequestOptions) =>
      this.send<T.Wallet>({ method: "POST", path: `/wallets/${seg(id)}/close`, body: {} }, o),
    statement: (id: string, params: { start?: string; end?: string } = {}, o?: RequestOptions) =>
      this.send<T.Statement>({ method: "GET", path: `/wallets/${seg(id)}/statement`, query: params }, o),
  };

  readonly transfers = {
    create: (input: T.TransferInput, o?: MutationOptions) => {
      assertAmount(input.amount);
      return this.mutate<T.Transaction>({ method: "POST", path: "/transfers", body: input }, o);
    },
    get: (id: string, o?: RequestOptions) =>
      this.send<T.TransactionDetail>({ method: "GET", path: `/transfers/${seg(id)}` }, o),
  };

  readonly transactions = {
    list: (params: T.TransactionListParams = {}, o?: RequestOptions) =>
      this.send<T.Page<T.Transaction>>({ method: "GET", path: "/transactions", query: params }, o),
    get: (id: string, o?: RequestOptions) =>
      this.send<T.TransactionDetail>({ method: "GET", path: `/transactions/${seg(id)}` }, o),
  };

  readonly holds = {
    list: (params: T.ListParams & { status?: T.HoldStatus; wallet_id?: string } = {}, o?: RequestOptions) =>
      this.send<T.Page<T.Hold>>({ method: "GET", path: "/holds", query: params }, o),
    get: (id: string, o?: RequestOptions) => this.send<T.Hold>({ method: "GET", path: `/holds/${seg(id)}` }, o),
    create: (input: T.HoldInput, o?: MutationOptions) => {
      assertAmount(input.amount);
      return this.mutate<T.Hold>({ method: "POST", path: "/holds", body: input }, o);
    },
    capture: (id: string, amount?: number, o?: MutationOptions) => {
      if (amount !== undefined) assertAmount(amount);
      return this.mutate<T.Hold>({ method: "POST", path: `/holds/${seg(id)}/capture`, body: { amount } }, o);
    },
    release: (id: string, o?: MutationOptions) =>
      this.mutate<T.Hold>({ method: "POST", path: `/holds/${seg(id)}/release`, body: {} }, o),
  };

  readonly reversals = {
    create: (input: T.ReversalInput, o?: MutationOptions) => {
      if (input.amount !== undefined) assertAmount(input.amount);
      return this.mutate<T.Transaction>({ method: "POST", path: "/reversals", body: input }, o);
    },
  };

  readonly accounts = {
    list: (
      params: T.ListParams & { type?: T.AccountType; currency?: string; include_wallets?: boolean } = {},
      o?: RequestOptions,
    ) => this.send<T.Page<T.Account>>({ method: "GET", path: "/accounts", query: params }, o),
    get: (id: string, o?: RequestOptions) => this.send<T.Account>({ method: "GET", path: `/accounts/${seg(id)}` }, o),
    create: (input: { code: string; name: string; type: T.AccountType; currency: string }, o?: RequestOptions) =>
      this.send<T.Account>({ method: "POST", path: "/accounts", body: input }, o),
    statement: (id: string, params: { start?: string; end?: string } = {}, o?: RequestOptions) =>
      this.send<T.Statement>({ method: "GET", path: `/accounts/${seg(id)}/statement`, query: params }, o),
  };

  readonly journalEntries = {
    list: (
      params: T.ListParams & { kind?: string; phase?: "pending" | "posted"; account_id?: string } = {},
      o?: RequestOptions,
    ) => this.send<T.Page<T.JournalEntry>>({ method: "GET", path: "/journal-entries", query: params }, o),
    get: (id: string, o?: RequestOptions) =>
      this.send<T.JournalEntry>({ method: "GET", path: `/journal-entries/${seg(id)}` }, o),
    createManual: (input: T.ManualEntryInput, o?: MutationOptions) =>
      this.mutate<T.JournalEntry>({ method: "POST", path: "/journal-entries", body: input }, o),
  };

  readonly reconciliation = {
    run: (o?: RequestOptions) =>
      this.send<T.ReconciliationRun>({ method: "POST", path: "/reconciliation/runs", body: {} }, o),
    list: (params: T.ListParams = {}, o?: RequestOptions) =>
      this.send<T.Page<T.ReconciliationRun>>({ method: "GET", path: "/reconciliation/runs", query: params }, o),
    get: (id: string, o?: RequestOptions) =>
      this.send<T.ReconciliationRun>({ method: "GET", path: `/reconciliation/runs/${seg(id)}` }, o),
  };

  readonly auditEvents = {
    list: (
      params: T.ListParams & { action?: string; target_id?: string; actor_id?: string } = {},
      o?: RequestOptions,
    ) => this.send<T.Page<T.AuditEvent>>({ method: "GET", path: "/audit-events", query: params }, o),
  };

  readonly overview = {
    get: (days = 30, o?: RequestOptions) =>
      this.send<T.Overview>({ method: "GET", path: "/overview", query: { days } }, o),
  };

  readonly currencies = {
    list: (o?: RequestOptions) => this.send<T.CurrencyInfo[]>({ method: "GET", path: "/currencies" }, o),
  };
}

/** Iterate every item across pages: `for await (const w of paginate((c) => client.wallets.list({ cursor: c })))`. */
export async function* paginate<I>(fetchPage: (cursor?: string) => Promise<T.Page<I>>): AsyncGenerator<I> {
  let cursor: string | undefined;
  for (;;) {
    const page = await fetchPage(cursor);
    yield* page.data;
    if (!page.has_more || !page.next_cursor) return;
    cursor = page.next_cursor;
  }
}
