import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { WaltrixApiError, WaltrixUnknownOutcomeError, newIdempotencyKey, parseMoney, type Wallet } from "@waltrix/sdk";
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  CheckCircle2,
  Fingerprint,
  HelpCircle,
  Loader2,
  RefreshCw,
  Send,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import { Controller, useForm } from "react-hook-form";
import { Link, useSearchParams } from "react-router-dom";
import { z } from "zod";

import { ErrorState } from "@/components/ui/data";
import { Select } from "@/components/ui/overlays";
import { Badge, Button, Card, Field, Input, PageHeader, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { humanError } from "@/lib/errors";
import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

import {
  AUTO_VERIFY_ATTEMPTS,
  initialTransferState,
  isUnresolved,
  transferReducer,
  verifyDelayMs,
  type TransferDraft,
  type TransferState,
} from "./machine";

const schema = z
  .object({
    source: z.string().min(1, "Choose the wallet to send from"),
    destination: z.string().min(1, "Choose the recipient wallet"),
    amount: z.string().trim().min(1, "Enter an amount"),
    description: z.string().max(500).optional(),
  })
  .refine((v) => v.source !== v.destination, {
    path: ["destination"],
    message: "Recipient must differ from the source",
  });
type FormValues = z.infer<typeof schema>;

function WalletOption({ w }: { w: Wallet }) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      <span className="truncate">{w.name}</span>
      <span className="font-mono text-xs text-faint">{w.owner_reference}</span>
    </span>
  );
}

function Outcome({
  state,
  wallets,
  onVerify,
  onReset,
  onEdit,
}: {
  state: TransferState;
  wallets: Map<string, Wallet>;
  onVerify: () => void;
  onReset: () => void;
  onEdit: () => void;
}) {
  if (state.kind === "edit" || state.kind === "review") return null;
  const d = state.draft;
  const amount = formatMoney(d.amount, d.currency);
  const route = `${wallets.get(d.sourceWalletId)?.name ?? "source"} → ${wallets.get(d.destinationWalletId)?.name ?? "destination"}`;

  const view = {
    submitting: {
      icon: <Loader2 className="size-7 animate-spin text-primary" />,
      tone: "border-primary/25 bg-primary-soft",
      title: state.kind === "submitting" && state.verifying ? "Verifying the result…" : "Processing transfer…",
      body: "Waiting for the ledger to confirm. Do not close this page.",
    },
    success: {
      icon: <CheckCircle2 className="size-7 text-success" />,
      tone: "border-success/25 bg-success-soft",
      title: "Transfer posted",
      body: `${amount} moved ${route}. The journal entry is final.`,
    },
    failed: {
      icon: <XCircle className="size-7 text-danger" />,
      tone: "border-danger/30 bg-danger-soft",
      title: "Transfer failed",
      body:
        state.kind === "failed"
          ? `${humanError(new WaltrixApiError(422, state.code, state.message))} No money moved.`
          : "",
    },
    rejected: {
      icon: <AlertTriangle className="size-7 text-warning" />,
      tone: "border-warning/30 bg-warning-soft",
      title: "Request not accepted",
      body: state.kind === "rejected" ? `${state.message} Nothing was executed.` : "",
    },
    unknown: {
      icon: <HelpCircle className="size-7 text-warning" />,
      tone: "border-warning/30 bg-warning-soft",
      title: "Result unknown",
      body:
        "We did not get a definitive answer, so we cannot say whether money moved. Verifying re-sends the same " +
        "request with the same idempotency key: it returns the original outcome and can never transfer twice.",
    },
  }[state.kind];

  return (
    <div role="status" aria-live="polite" className="space-y-5 animate-fade-up">
      <div className={cn("flex gap-4 rounded-xl border p-5", view.tone)}>
        <div className="shrink-0">{view.icon}</div>
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-fg">{view.title}</h2>
          <p className="mt-1 text-sm text-fg-2">{view.body}</p>
        </div>
      </div>
      <dl className="grid gap-3 rounded-xl border border-border p-4 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-faint">Amount</dt>
          <dd className="tabular font-medium text-fg">{amount}</dd>
        </div>
        <div>
          <dt className="text-xs text-faint">Route</dt>
          <dd className="truncate text-fg">{route}</dd>
        </div>
        {"key" in state && (
          <div className="sm:col-span-2">
            <dt className="flex items-center gap-1 text-xs text-faint">
              <Fingerprint className="size-3" /> Idempotency key
            </dt>
            <dd className="break-all font-mono text-xs text-muted">{state.key}</dd>
          </div>
        )}
        {state.kind === "success" && (
          <div className="sm:col-span-2">
            <dt className="text-xs text-faint">Transaction</dt>
            <dd>
              <Link className="font-mono text-xs text-primary hover:underline" to={`/transactions/${state.tx.id}`}>
                {state.tx.id}
              </Link>
            </dd>
          </div>
        )}
        {state.kind === "failed" && state.transactionId && (
          <div className="sm:col-span-2">
            <dt className="text-xs text-faint">Recorded failed transaction</dt>
            <dd>
              <Link
                className="font-mono text-xs text-primary hover:underline"
                to={`/transactions/${state.transactionId}`}
              >
                {state.transactionId}
              </Link>
            </dd>
          </div>
        )}
      </dl>
      <div className="flex flex-wrap gap-2">
        {state.kind === "unknown" && (
          <Button variant="primary" onClick={onVerify}>
            <RefreshCw /> Check again
          </Button>
        )}
        {state.kind === "rejected" && (
          <Button onClick={onEdit}>
            <ArrowLeft /> Edit transfer
          </Button>
        )}
        {(state.kind === "success" || state.kind === "failed" || state.kind === "rejected") && (
          <Button variant={state.kind === "success" ? "primary" : "secondary"} onClick={onReset}>
            New transfer
          </Button>
        )}
      </div>
    </div>
  );
}

export function TransferPage() {
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const [state, dispatch] = useReducer(transferReducer, initialTransferState);
  const inFlight = useRef(false);
  const walletsQuery = useQuery({
    queryKey: ["wallets", "transfer-options"],
    queryFn: () => api.wallets.list({ limit: 100, status: "active" }),
  });
  const wallets = useMemo(() => new Map((walletsQuery.data?.data ?? []).map((w) => [w.id, w])), [walletsQuery.data]);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { source: params.get("from") ?? "", destination: "", amount: "", description: "" },
  });
  const source = wallets.get(form.watch("source"));
  const destinationOptions = [...wallets.values()].filter(
    (w) => w.id !== source?.id && (!source || w.currency === source.currency),
  );

  // Warn before leaving while an operation is in flight or unresolved.
  useEffect(() => {
    if (!isUnresolved(state)) return;
    const handler = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [state]);

  const execute = useCallback(
    async (draft: TransferDraft, key: string, verifying: boolean) => {
      if (inFlight.current) return; // guards double submission even across fast clicks
      inFlight.current = true;
      try {
        const tx = await api.transfers.create(
          {
            source_wallet_id: draft.sourceWalletId,
            destination_wallet_id: draft.destinationWalletId,
            amount: draft.amount,
            currency: draft.currency,
            description: draft.description || undefined,
          },
          { idempotencyKey: key },
        );
        dispatch({ type: "SUCCEEDED", tx });
        void qc.invalidateQueries();
      } catch (err) {
        if (err instanceof WaltrixUnknownOutcomeError) {
          dispatch({ type: "UNKNOWN", message: humanError(err) });
        } else if (err instanceof WaltrixApiError && err.isBusinessFailure) {
          dispatch({ type: "FAILED", code: err.code, message: err.message, transactionId: err.transactionId });
          void qc.invalidateQueries();
        } else if (verifying && err instanceof WaltrixApiError && err.status >= 500) {
          dispatch({ type: "UNKNOWN", message: humanError(err) });
        } else {
          dispatch({ type: "REJECTED", message: humanError(err) });
        }
      } finally {
        inFlight.current = false;
      }
    },
    [qc],
  );

  // Run the request whenever we enter `submitting`.
  useEffect(() => {
    if (state.kind === "submitting") void execute(state.draft, state.key, state.verifying);
  }, [state, execute]);

  // Automatic verification with backoff when the outcome is unknown.
  useEffect(() => {
    if (state.kind !== "unknown" || state.attempt > AUTO_VERIFY_ATTEMPTS) return;
    const t = setTimeout(() => dispatch({ type: "VERIFY" }), verifyDelayMs(state.attempt));
    return () => clearTimeout(t);
  }, [state]);

  const onReview = form.handleSubmit((values) => {
    const src = wallets.get(values.source);
    const dst = wallets.get(values.destination);
    if (!src || !dst) return;
    const amount = parseMoney(values.amount, src.currency);
    if (amount === null || amount <= 0) {
      form.setError("amount", {
        message: `Enter a positive ${src.currency} amount (max ${src.currency === "JPY" ? "0" : "2"} decimals)`,
      });
      return;
    }
    if (amount > src.balance.available) {
      form.setError("amount", {
        message: `Exceeds available balance of ${formatMoney(src.balance.available, src.currency)}`,
      });
      return;
    }
    dispatch({
      type: "REVIEW",
      key: newIdempotencyKey(),
      draft: {
        sourceWalletId: src.id,
        destinationWalletId: dst.id,
        amount,
        currency: src.currency,
        description: values.description?.trim() || undefined,
      },
    });
  });

  const reset = () => {
    form.reset({ source: "", destination: "", amount: "", description: "" });
    dispatch({ type: "RESET" });
  };

  return (
    <>
      <PageHeader
        title="Transfer funds"
        description="Move money between two wallets of this organization. Every transfer is a balanced, immutable journal entry."
      />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="p-6">
          {walletsQuery.error ? (
            <ErrorState error={walletsQuery.error} onRetry={() => void walletsQuery.refetch()} />
          ) : !walletsQuery.data ? (
            <div className="space-y-4">
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
            </div>
          ) : state.kind === "edit" ? (
            <form onSubmit={onReview} className="space-y-5" noValidate aria-label="Transfer details">
              <Field
                label="From"
                htmlFor="source"
                error={form.formState.errors.source?.message}
                hint={source ? `Available: ${formatMoney(source.balance.available, source.currency)}` : undefined}
              >
                <Controller
                  control={form.control}
                  name="source"
                  render={({ field }) => (
                    <Select
                      id="source"
                      value={field.value || undefined}
                      onValueChange={(v) => {
                        field.onChange(v);
                        form.setValue("destination", "");
                      }}
                      placeholder="Select source wallet"
                      invalid={Boolean(form.formState.errors.source)}
                      options={[...wallets.values()].map((w) => ({
                        value: w.id,
                        label: <WalletOption w={w} />,
                        hint: formatMoney(w.balance.available, w.currency),
                      }))}
                    />
                  )}
                />
              </Field>
              <div className="flex justify-center text-faint">
                <ArrowDown className="size-4" />
              </div>
              <Field label="To" htmlFor="destination" error={form.formState.errors.destination?.message}>
                <Controller
                  control={form.control}
                  name="destination"
                  render={({ field }) => (
                    <Select
                      id="destination"
                      value={field.value || undefined}
                      onValueChange={field.onChange}
                      placeholder={source ? `Select a ${source.currency} wallet` : "Select source first"}
                      invalid={Boolean(form.formState.errors.destination)}
                      options={destinationOptions.map((w) => ({
                        value: w.id,
                        label: <WalletOption w={w} />,
                        hint: w.currency,
                      }))}
                    />
                  )}
                />
              </Field>
              <Field
                label={`Amount${source ? ` (${source.currency})` : ""}`}
                htmlFor="amount"
                error={form.formState.errors.amount?.message}
              >
                <Input
                  id="amount"
                  inputMode="decimal"
                  autoComplete="off"
                  placeholder="0.00"
                  className="tabular h-12 text-lg font-medium"
                  aria-invalid={Boolean(form.formState.errors.amount) || undefined}
                  {...form.register("amount")}
                />
              </Field>
              <Field label="Description (optional)" htmlFor="description">
                <Input
                  id="description"
                  maxLength={500}
                  placeholder="What is this for?"
                  {...form.register("description")}
                />
              </Field>
              <Button type="submit" variant="primary" size="lg" className="w-full">
                Review transfer
              </Button>
            </form>
          ) : state.kind === "review" ? (
            <section aria-labelledby="review-title" className="space-y-6 animate-fade-up">
              <div>
                <h2 id="review-title" className="text-base font-semibold text-fg">
                  Review and confirm
                </h2>
                <p className="mt-1 text-sm text-muted">
                  Check the recipient carefully. Posted transfers can only be undone by a reversal.
                </p>
              </div>
              <div className="rounded-xl border border-border bg-bg/40 p-5 text-center">
                <div className="text-xs uppercase tracking-wider text-faint">You are sending</div>
                <div className="tabular mt-1 text-3xl font-semibold tracking-tight text-fg">
                  {formatMoney(state.draft.amount, state.draft.currency)}
                </div>
              </div>
              <dl className="divide-y divide-border rounded-xl border border-border text-sm">
                {[
                  ["From", wallets.get(state.draft.sourceWalletId)],
                  ["To", wallets.get(state.draft.destinationWalletId)],
                ].map(([label, w]) => {
                  const wallet = w as Wallet | undefined;
                  return (
                    <div key={label as string} className="flex items-center justify-between gap-4 px-4 py-3">
                      <dt className="text-muted">{label as string}</dt>
                      <dd className="min-w-0 text-right">
                        <div className="truncate font-medium text-fg">{wallet?.name}</div>
                        <div className="font-mono text-xs text-faint">
                          {wallet?.owner_reference} · {wallet?.id.slice(0, 8)}
                        </div>
                      </dd>
                    </div>
                  );
                })}
                <div className="flex justify-between px-4 py-3">
                  <dt className="text-muted">Source balance after</dt>
                  <dd className="tabular text-fg">
                    {formatMoney(
                      (wallets.get(state.draft.sourceWalletId)?.balance.available ?? 0) - state.draft.amount,
                      state.draft.currency,
                    )}
                  </dd>
                </div>
                {state.draft.description && (
                  <div className="flex justify-between gap-4 px-4 py-3">
                    <dt className="text-muted">Description</dt>
                    <dd className="truncate text-fg">{state.draft.description}</dd>
                  </div>
                )}
              </dl>
              <div className="flex gap-2">
                <Button onClick={() => dispatch({ type: "EDIT" })}>
                  <ArrowLeft /> Edit
                </Button>
                <Button variant="primary" className="flex-1" onClick={() => dispatch({ type: "SUBMIT" })}>
                  <Send /> Confirm transfer
                </Button>
              </div>
            </section>
          ) : (
            <Outcome
              state={state}
              wallets={wallets}
              onVerify={() => dispatch({ type: "VERIFY" })}
              onReset={reset}
              onEdit={() => dispatch({ type: "EDIT" })}
            />
          )}
        </Card>
        <aside className="space-y-4">
          <Card className="p-5">
            <h3 className="text-sm font-semibold text-fg">How this stays safe</h3>
            <ul className="mt-3 space-y-3 text-[13px] text-muted">
              <li className="flex gap-2">
                <Badge tone="primary" className="size-5 shrink-0 justify-center self-start p-0">
                  1
                </Badge>{" "}
                A unique idempotency key is attached when you review. Retries reuse it.
              </li>
              <li className="flex gap-2">
                <Badge tone="primary" className="size-5 shrink-0 justify-center self-start p-0">
                  2
                </Badge>{" "}
                The server locks both accounts, checks funds and posts debit + credit atomically.
              </li>
              <li className="flex gap-2">
                <Badge tone="primary" className="size-5 shrink-0 justify-center self-start p-0">
                  3
                </Badge>{" "}
                Success is shown only after the server confirms it. Unclear results are verified, never assumed.
              </li>
            </ul>
          </Card>
          {wallets.size < 2 && walletsQuery.data && (
            <Card className="p-5 text-[13px] text-muted">
              You need at least two active wallets.{" "}
              <Link to="/wallets" className="text-primary hover:underline">
                Create wallets
              </Link>
              .
            </Card>
          )}
        </aside>
      </div>
    </>
  );
}
