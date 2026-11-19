/** Base class of every SDK error. */
export class WaltrixError extends Error {
  override name = "WaltrixError";
}

/** The server answered with an error. The outcome is known. */
export class WaltrixApiError extends WaltrixError {
  override name = "WaltrixApiError";
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
    readonly correlationId: string | null = null,
  ) {
    super(message);
  }

  /**
   * A business rule rejected the operation (e.g. insufficient_funds). It is final
   * and recorded; retrying with the same idempotency key returns the same failure.
   */
  get isBusinessFailure(): boolean {
    return this.status === 422 && this.code !== "validation_failed";
  }

  /** Id of the FAILED transaction the server recorded, when there is one. */
  get transactionId(): string | null {
    const id = this.details["transaction_id"];
    return typeof id === "string" ? id : null;
  }
}

/** A read could not reach the server after all retries. */
export class WaltrixNetworkError extends WaltrixError {
  override name = "WaltrixNetworkError";
}

/**
 * A mutation got no definitive answer (timeout, network failure, 5xx, or the caller
 * aborted after the request was sent). The operation MAY have been applied.
 * Retry with the same `idempotencyKey` (it cannot apply twice) or look it up.
 */
export class WaltrixUnknownOutcomeError extends WaltrixError {
  override name = "WaltrixUnknownOutcomeError";
  constructor(
    message: string,
    readonly idempotencyKey: string | null,
    readonly aborted = false,
    options?: { cause?: unknown },
  ) {
    super(message, options);
  }
}

interface ErrorBody {
  error?: { code?: string; message?: string; details?: Record<string, unknown>; correlation_id?: string };
}

export function errorFromResponse(status: number, body: unknown): WaltrixApiError {
  const err = (body as ErrorBody | null)?.error ?? {};
  return new WaltrixApiError(
    status,
    err.code ?? "unknown_error",
    err.message ?? `request failed with status ${status}`,
    err.details ?? {},
    err.correlation_id ?? null,
  );
}
