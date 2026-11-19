"""Example: a marketplace checkout integrating Waltrix with the Python SDK.

Flow: create buyer + seller wallets, fund the buyer (SIMULATED funding),
authorize (hold) at checkout, capture what was actually shipped, refund part
of it, then verify with reconciliation.

    WALTRIX_API_KEY=wtx_key_... python examples/python-integration/checkout.py
"""

from __future__ import annotations

import os
import uuid

from waltrix import OperationFailedError, UnknownOutcomeError, Waltrix


def money(amount: int) -> str:
    return f"${amount / 100:,.2f}"  # display only; the API works in integer cents


def main() -> None:
    client = Waltrix(
        os.environ["WALTRIX_API_KEY"], base_url=os.environ.get("WALTRIX_URL", "http://127.0.0.1:4820")
    )
    run = uuid.uuid4().hex[:8]  # makes the example re-runnable

    buyer = client.wallets.create("Example Buyer", f"buyer_{run}", "USD", metadata={"synthetic": True})
    seller = client.wallets.create("Example Seller", f"seller_{run}", "USD", metadata={"synthetic": True})
    client.wallets.credit(
        buyer["id"], 50_00, "USD", description="Simulated top-up", idempotency_key=f"topup-{run}"
    )

    # Checkout: reserve the order total. Our own order id is the idempotency key, so a
    # retried checkout (double click, worker restart) can never reserve twice.
    order_id = f"order-{run}"
    try:
        hold = client.holds.create(
            buyer["id"], seller["id"], 42_00, "USD", idempotency_key=f"{order_id}:hold"
        )
    except UnknownOutcomeError as exc:
        # The network failed and we do not know if the hold exists. Retrying with the
        # same key is safe: it either creates it or returns the existing one.
        hold = client.holds.create(
            buyer["id"], seller["id"], 42_00, "USD", idempotency_key=exc.idempotency_key
        )
    print(
        "held",
        money(hold["amount"]),
        "available now",
        money(client.wallets.balance(buyer["id"])["available"]),
    )

    # Only part of the order shipped: capture 30.00, the remaining 12.00 is released.
    captured = client.holds.capture(hold["id"], amount=30_00, idempotency_key=f"{order_id}:capture")
    print("captured", money(captured["captured_amount"] or 0))

    # A damaged item: partial refund of 5.00 via a reversal (history is preserved).
    refund = client.reversals.create(
        captured["transaction_id"], amount=5_00, reason="damaged item", idempotency_key=f"{order_id}:refund-1"
    )
    print("refund", refund["id"], refund["status"])

    try:
        client.transfers.create(
            buyer["id"], seller["id"], 10_000_00, "USD", idempotency_key=f"{order_id}:big"
        )
    except OperationFailedError as exc:
        print("expected failure:", exc.code, "recorded as", exc.transaction_id)

    print("buyer", client.wallets.balance(buyer["id"]))
    print("seller", client.wallets.balance(seller["id"]))
    history = [t["type"] for t in client.paginate(client.transactions.list, wallet_id=buyer["id"], limit=10)]
    print("buyer history:", history)


if __name__ == "__main__":
    main()
