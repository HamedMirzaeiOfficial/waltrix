/**
 * Example: payouts service in Node using @waltrix/sdk.
 *
 *   WALTRIX_API_KEY=wtx_key_... npm start -w waltrix-typescript-integration-example
 */
import { Waltrix, WaltrixApiError, WaltrixUnknownOutcomeError, formatMoney, paginate } from "@waltrix/sdk";

const client = new Waltrix({
  apiKey: process.env.WALTRIX_API_KEY!,
  baseUrl: process.env.WALTRIX_URL ?? "http://127.0.0.1:4820",
});

async function payout(walletId: string, amount: number, payoutId: string) {
  // The payout id from our own database is the idempotency key: safe across retries and restarts.
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      return await client.wallets.debit(
        walletId,
        { amount, currency: "USD", reference: payoutId },
        { idempotencyKey: `payout:${payoutId}` },
      );
    } catch (err) {
      if (err instanceof WaltrixUnknownOutcomeError) continue; // same key -> cannot double pay
      throw err;
    }
  }
  throw new Error(`payout ${payoutId} outcome still unknown; check status later`);
}

const run = crypto.randomUUID().slice(0, 8);
const wallet = await client.wallets.create({
  name: "Example Creator",
  owner_reference: `creator_${run}`,
  currency: "USD",
});
await client.wallets.credit(
  wallet.id,
  { amount: 25_00, currency: "USD", description: "Simulated earnings" },
  { idempotencyKey: `earnings:${run}` },
);

const tx = await payout(wallet.id, 10_00, `po_${run}`);
console.log("payout", tx.id, tx.status, formatMoney(tx.amount, tx.currency));

try {
  await payout(wallet.id, 99_00, `po_${run}_2`);
} catch (err) {
  if (err instanceof WaltrixApiError && err.isBusinessFailure) console.log("rejected:", err.code, err.transactionId);
}

const balance = await client.wallets.balance(wallet.id);
console.log("balance", formatMoney(balance.available, "USD"));
for await (const t of paginate((cursor) => client.transactions.list({ wallet_id: wallet.id, cursor }))) {
  console.log(" -", t.type, t.status, formatMoney(t.amount, t.currency));
}
