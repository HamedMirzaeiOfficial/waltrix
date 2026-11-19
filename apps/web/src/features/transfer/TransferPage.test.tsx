import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WaltrixApiError, WaltrixUnknownOutcomeError, type Wallet } from "@waltrix/sdk";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TransferPage } from "./TransferPage";

const create = vi.fn();
const wallet = (id: string, name: string, available: number): Wallet => ({
  id,
  name,
  owner_reference: `cust_${id}`,
  currency: "USD",
  status: "active",
  account_id: `acc_${id}`,
  balance: { currency: "USD", posted: available, pending_outgoing: 0, pending_incoming: 0, available },
  metadata: {},
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
});

vi.mock("@/lib/api", () => ({
  api: {
    wallets: {
      list: vi.fn(async () => ({
        data: [wallet("w-alice", "Alice", 10_000), wallet("w-bob", "Bob", 0)],
        next_cursor: null,
        has_more: false,
      })),
    },
    transfers: { create: (...args: unknown[]) => create(...args) },
  },
}));

// Radix Select is awkward in jsdom; the page is opened with ?from= and we pick the destination via keyboard.
function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/transfer?from=w-alice"]}>
        <TransferPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function fillAndReview(amount: string) {
  const user = userEvent.setup();
  renderPage();
  await screen.findByText(/Available: \$100\.00/);
  await user.click(screen.getByRole("combobox", { name: /to/i }));
  await user.click(await screen.findByRole("option", { name: /Bob/ }));
  await user.type(screen.getByLabelText(/Amount/), amount);
  await user.click(screen.getByRole("button", { name: /review transfer/i }));
  return user;
}

describe("TransferPage", () => {
  beforeEach(() => create.mockReset());

  it("rejects amounts with too many decimals before reviewing", async () => {
    await fillAndReview("12.345");
    expect(await screen.findByRole("alert")).toHaveTextContent(/positive USD amount/);
    expect(create).not.toHaveBeenCalled();
  });

  it("rejects amounts above the available balance", async () => {
    await fillAndReview("100.01");
    expect(await screen.findByRole("alert")).toHaveTextContent(/Exceeds available balance/);
  });

  it("shows a review screen, then success only after the server confirms; double clicks send once", async () => {
    let resolve!: (v: unknown) => void;
    create.mockImplementationOnce(() => new Promise((r) => (resolve = r)));
    await fillAndReview("12.50");
    expect(await screen.findByText("Review and confirm")).toBeInTheDocument();
    expect(screen.getByText("$12.50")).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: /confirm transfer/i });
    // Two clicks in the same tick, as a fast double click would deliver them.
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(await screen.findByText(/Processing transfer/)).toBeInTheDocument();
    expect(screen.queryByText(/Transfer posted/)).not.toBeInTheDocument();
    resolve({ id: "tx-1", status: "posted" });
    expect(await screen.findByText("Transfer posted")).toBeInTheDocument();
    expect(create).toHaveBeenCalledTimes(1);
    const [body, opts] = create.mock.calls[0]!;
    expect(body).toMatchObject({
      source_wallet_id: "w-alice",
      destination_wallet_id: "w-bob",
      amount: 1250,
      currency: "USD",
    });
    expect(opts.idempotencyKey).toMatch(/[0-9a-f-]{32,}/);
    // Nothing re-sends the transfer after it is confirmed (refetches, re-renders).
    await new Promise((r) => setTimeout(r, 300));
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("never claims success when the outcome is unknown, and verifies with the same key", async () => {
    create
      .mockRejectedValueOnce(new WaltrixUnknownOutcomeError("timeout", "k"))
      .mockResolvedValueOnce({ id: "tx-2", status: "posted" });
    const user = await fillAndReview("5");
    await user.click(await screen.findByRole("button", { name: /confirm transfer/i }));
    expect(await screen.findByText("Result unknown")).toBeInTheDocument();
    expect(screen.queryByText("Transfer posted")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /check again/i }));
    expect(await screen.findByText("Transfer posted")).toBeInTheDocument();
    expect(create).toHaveBeenCalledTimes(2);
    expect(create.mock.calls[0]![1].idempotencyKey).toBe(create.mock.calls[1]![1].idempotencyKey);
  });

  it("shows a confirmed failure with the recorded transaction", async () => {
    create.mockRejectedValueOnce(new WaltrixApiError(422, "insufficient_funds", "no", { transaction_id: "tx-failed" }));
    const user = await fillAndReview("50");
    await user.click(await screen.findByRole("button", { name: /confirm transfer/i }));
    expect(await screen.findByText("Transfer failed")).toBeInTheDocument();
    expect(screen.getByText(/No money moved/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("link", { name: "tx-failed" })).toBeInTheDocument());
  });
});
