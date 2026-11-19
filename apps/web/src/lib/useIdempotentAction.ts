import { useQueryClient } from "@tanstack/react-query";
import { WaltrixApiError, WaltrixUnknownOutcomeError, newIdempotencyKey } from "@waltrix/sdk";
import { useCallback, useRef, useState } from "react";

import { humanError } from "./errors";
import { useLanguageLock } from "./lang";

export type ActionStatus = "idle" | "pending" | "success" | "failed" | "rejected" | "unknown";

/**
 * One money-moving action (credit, debit, hold, capture, release, reversal).
 *
 * - One idempotency key per action session, kept across retries ("Try again" after
 *   an unknown outcome replays safely). `reset()` starts a new session/key.
 * - `pending` blocks re-entry, so double clicks cannot send twice.
 * - Distinguishes confirmed success, confirmed business failure, rejection
 *   (nothing executed) and unknown outcome.
 */
export function useIdempotentAction<T>() {
  const qc = useQueryClient();
  const [key, setKey] = useState(newIdempotencyKey);
  const [status, setStatus] = useState<ActionStatus>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [result, setResult] = useState<T | null>(null);
  const [failedTransactionId, setFailedTx] = useState<string | null>(null);
  const busy = useRef(false);
  useLanguageLock(status === "pending" || status === "unknown");

  const run = useCallback(
    async (fn: (idempotencyKey: string) => Promise<T>): Promise<T | null> => {
      if (busy.current) return null;
      busy.current = true;
      setStatus("pending");
      setMessage(null);
      try {
        const value = await fn(key);
        setResult(value);
        setStatus("success");
        void qc.invalidateQueries();
        return value;
      } catch (err) {
        setMessage(humanError(err));
        if (err instanceof WaltrixUnknownOutcomeError) setStatus("unknown");
        else if (err instanceof WaltrixApiError && err.isBusinessFailure) {
          setFailedTx(err.transactionId);
          setStatus("failed");
          void qc.invalidateQueries();
        } else setStatus("rejected");
        return null;
      } finally {
        busy.current = false;
      }
    },
    [key, qc],
  );

  const reset = useCallback(() => {
    setKey(newIdempotencyKey());
    setStatus("idle");
    setMessage(null);
    setResult(null);
    setFailedTx(null);
  }, []);

  return { key, status, message, result, failedTransactionId, run, reset, pending: status === "pending" };
}
