import { describe, expect, it } from "vitest";

import { initialTransferState, isUnresolved, transferReducer, verifyDelayMs, type TransferState } from "./machine";

const draft = { sourceWalletId: "a", destinationWalletId: "b", amount: 1250, currency: "USD" };
const review = transferReducer(initialTransferState, { type: "REVIEW", draft, key: "key-1" });
const submitting = transferReducer(review, { type: "SUBMIT" });

describe("transfer state machine", () => {
  it("goes edit -> review -> submitting with the same key", () => {
    expect(review).toMatchObject({ kind: "review", key: "key-1" });
    expect(submitting).toMatchObject({ kind: "submitting", key: "key-1", attempt: 1 });
  });

  it("ignores a second SUBMIT while submitting (no double submission)", () => {
    expect(transferReducer(submitting, { type: "SUBMIT" })).toBe(submitting);
  });

  it("only reaches success from a server confirmation", () => {
    expect(transferReducer(review, { type: "SUCCEEDED", tx: { id: "t", status: "posted" } })).toBe(review);
    expect(transferReducer(submitting, { type: "SUCCEEDED", tx: { id: "t", status: "posted" } }).kind).toBe("success");
  });

  it("verifies an unknown outcome with the SAME idempotency key", () => {
    const unknown = transferReducer(submitting, { type: "UNKNOWN", message: "timeout" });
    expect(unknown).toMatchObject({ kind: "unknown", key: "key-1" });
    expect(isUnresolved(unknown)).toBe(true);
    const verifying = transferReducer(unknown, { type: "VERIFY" });
    expect(verifying).toMatchObject({ kind: "submitting", key: "key-1", attempt: 2, verifying: true });
  });

  it("editing discards the key; a new review gets a new one", () => {
    const edit = transferReducer(review, { type: "EDIT" });
    expect(edit).toEqual({ kind: "edit", draft });
    const again = transferReducer(edit, { type: "REVIEW", draft: { ...draft, amount: 99 }, key: "key-2" });
    expect(again).toMatchObject({ key: "key-2" });
  });

  it("cannot reset while a request is in flight", () => {
    expect(transferReducer(submitting, { type: "RESET" })).toBe(submitting);
  });

  it("records business failures with the failed transaction id", () => {
    const failed = transferReducer(submitting, {
      type: "FAILED",
      code: "insufficient_funds",
      message: "no",
      transactionId: "t-9",
    }) as Extract<TransferState, { kind: "failed" }>;
    expect(failed.kind).toBe("failed");
    expect(failed.transactionId).toBe("t-9");
    expect(isUnresolved(failed)).toBe(false);
  });

  it("backs off verification", () => {
    expect([1, 2, 3, 4, 10].map(verifyDelayMs)).toEqual([1000, 2000, 4000, 8000, 8000]);
  });
});
