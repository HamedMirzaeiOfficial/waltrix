import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  WaltrixApiError,
  parseMoney,
  type JournalEntry,
  type TransactionDetail,
  type TransactionStatus,
  type TransactionType,
} from "@waltrix/sdk";
import { ArrowLeftRight, RotateCcw, Search } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ActionResult } from "@/components/ActionResult";
import { DataTable, ErrorState, Money, Pager, StatusBadge, useCursorPager } from "@/components/ui/data";
import { Dialog, Select } from "@/components/ui/overlays";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  CopyId,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Skeleton,
} from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { humanError } from "@/lib/errors";
import { dateTime, formatMoney, humanize } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useIdempotentAction } from "@/lib/useIdempotentAction";
import { cn } from "@/lib/utils";

import { txColumns } from "./overview";

const STATUSES: TransactionStatus[] = ["posted", "pending", "failed", "reversed"];
const TYPES: TransactionType[] = ["transfer", "deposit", "withdrawal", "hold", "reversal"];

export function TransactionsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const pager = useCursorPager();
  const status = params.get("status") ?? "all";
  const type = params.get("type") ?? "all";
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [sort, setSort] = useState<"-created_at" | "created_at">("-created_at");
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v === "all" || !v) next.delete(k);
    else next.set(k, v);
    setParams(next, { replace: true });
    pager.reset();
  };
  const query = useQuery({
    queryKey: ["transactions", { status, type, search, sort, cursor: pager.cursor }],
    queryFn: () =>
      api.transactions.list({
        limit: 25,
        cursor: pager.cursor,
        status: status === "all" ? undefined : (status as TransactionStatus),
        type: type === "all" ? undefined : (type as TransactionType),
        search: search.trim() || undefined,
        sort,
      }),
    placeholderData: keepPreviousData,
  });
  return (
    <>
      <PageHeader
        title="Transactions"
        description="Every operation requested, including failed ones. Money movement itself lives in the ledger."
      />
      <Card>
        <div className="flex flex-col gap-3 border-b border-border p-4 lg:flex-row">
          <form
            className="relative flex-1"
            onSubmit={(e) => {
              e.preventDefault();
              set("q", search);
            }}
          >
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
            <Input
              aria-label="Search transactions"
              className="pl-9"
              placeholder="Search by id, reference or description - press Enter"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </form>
          <Select
            aria-label="Status"
            className="lg:w-40"
            value={status}
            onValueChange={(v) => set("status", v)}
            options={[
              { value: "all", label: "All statuses" },
              ...STATUSES.map((s) => ({ value: s, label: humanize(s) })),
            ]}
          />
          <Select
            aria-label="Type"
            className="lg:w-40"
            value={type}
            onValueChange={(v) => set("type", v)}
            options={[{ value: "all", label: "All types" }, ...TYPES.map((t) => ({ value: t, label: humanize(t) }))]}
          />
          <Select
            aria-label="Sort"
            className="lg:w-40"
            value={sort}
            onValueChange={(v) => {
              setSort(v as typeof sort);
              pager.reset();
            }}
            options={[
              { value: "-created_at", label: "Newest first" },
              { value: "created_at", label: "Oldest first" },
            ]}
          />
        </div>
        {query.error ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : (
          <DataTable
            caption="Transactions"
            columns={txColumns()}
            rows={query.data?.data}
            rowKey={(t) => t.id}
            onRowClick={(t) => navigate(`/transactions/${t.id}`)}
            empty={
              <EmptyState
                icon={<ArrowLeftRight />}
                title="No transactions match"
                description="Adjust the filters or search term."
              />
            }
          />
        )}
        <Pager
          page={pager.page}
          hasMore={query.data?.has_more ?? false}
          busy={query.isFetching}
          onPrev={pager.prev}
          onNext={() => pager.next(query.data?.next_cursor ?? null)}
        />
      </Card>
    </>
  );
}

export function EntryLines({ entry }: { entry: JournalEntry }) {
  const debits = entry.postings.filter((p) => p.direction === "debit").reduce((s, p) => s + p.amount, 0);
  const credits = entry.postings.filter((p) => p.direction === "credit").reduce((s, p) => s + p.amount, 0);
  const currency = entry.postings[0]?.currency ?? "USD";
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-sm">
        <caption className="sr-only">Postings of entry {entry.entry_number}</caption>
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-faint">
            <th scope="col" className="px-5 py-2 font-medium">
              Account
            </th>
            <th scope="col" className="px-5 py-2 text-right font-medium">
              Debit
            </th>
            <th scope="col" className="px-5 py-2 text-right font-medium">
              Credit
            </th>
          </tr>
        </thead>
        <tbody>
          {entry.postings.map((p) => (
            <tr key={p.line_no} className="border-b border-border/60">
              <td className="px-5 py-2.5">
                {p.wallet_id ? (
                  <Link to={`/wallets/${p.wallet_id}`} className="font-medium text-fg hover:text-primary">
                    {p.account_name}
                  </Link>
                ) : (
                  <span className="font-medium text-fg">{p.account_name}</span>
                )}
                <div className="font-mono text-xs text-faint">{p.account_code}</div>
              </td>
              <td className="px-5 py-2.5 text-right">
                {p.direction === "debit" ? <Money amount={p.amount} currency={p.currency} /> : ""}
              </td>
              <td className="px-5 py-2.5 text-right">
                {p.direction === "credit" ? <Money amount={p.amount} currency={p.currency} /> : ""}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="text-[13px]">
            <td className="px-5 py-2.5 text-muted">
              Totals{" "}
              {debits === credits ? (
                <Badge tone="success" className="ml-2">
                  Balanced
                </Badge>
              ) : (
                <Badge tone="danger" className="ml-2">
                  Unbalanced
                </Badge>
              )}
            </td>
            <td className="tabular px-5 py-2.5 text-right font-semibold text-fg">{formatMoney(debits, currency)}</td>
            <td className="tabular px-5 py-2.5 text-right font-semibold text-fg">{formatMoney(credits, currency)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function ReverseDialog({
  tx,
  open,
  onOpenChange,
}: {
  tx: TransactionDetail;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const action = useIdempotentAction<unknown>();
  const remaining = (tx.posted_amount ?? 0) - tx.reversed_amount;
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const done = action.status === "success" || action.status === "failed";
  const close = (o: boolean) => {
    if (action.pending) return;
    onOpenChange(o);
    if (!o) action.reset();
  };
  return (
    <Dialog
      open={open}
      onOpenChange={close}
      title="Reverse transaction"
      description={`Posts an opposite entry. The original stays in the journal. Up to ${formatMoney(remaining, tx.currency)} can be reversed.`}
    >
      <form
        className="space-y-4"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          const minor = amount.trim() ? parseMoney(amount, tx.currency) : remaining;
          if (minor === null || minor <= 0) return setError("Enter a positive amount");
          if (minor > remaining) return setError(`At most ${formatMoney(remaining, tx.currency)}`);
          setError(null);
          void action.run((key) =>
            api.reversals.create(
              { transaction_id: tx.id, amount: minor === remaining ? undefined : minor, reason: reason || undefined },
              { idempotencyKey: key },
            ),
          );
        }}
      >
        <Field
          label={`Amount (${tx.currency})`}
          htmlFor="rev-amount"
          error={error ?? undefined}
          hint="Leave empty for a full reversal."
        >
          <Input
            id="rev-amount"
            inputMode="decimal"
            className="tabular"
            placeholder={formatMoney(remaining, tx.currency)}
            value={amount}
            disabled={action.pending || done}
            onChange={(e) => setAmount(e.target.value)}
          />
        </Field>
        <Field label="Reason" htmlFor="rev-reason">
          <Input
            id="rev-reason"
            value={reason}
            maxLength={500}
            disabled={action.pending || done}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        <ActionResult
          status={action.status}
          message={action.message}
          failedTransactionId={action.failedTransactionId}
          success="Reversal posted."
        />
        <div className="flex justify-end gap-2">
          <Button type="button" onClick={() => close(false)} disabled={action.pending}>
            {done ? "Close" : "Cancel"}
          </Button>
          {!done && (
            <Button type="submit" variant="danger" loading={action.pending}>
              {action.status === "unknown" ? "Retry safely" : "Post reversal"}
            </Button>
          )}
        </div>
      </form>
    </Dialog>
  );
}

export function TransactionDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { can } = useSession();
  const [reversing, setReversing] = useState(false);
  const q = useQuery({ queryKey: ["transactions", id], queryFn: () => api.transactions.get(id) });
  if (q.error)
    return (
      <Card>
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </Card>
    );
  const t = q.data;
  const reversible = t && t.status === "posted" && t.type !== "reversal" && (t.posted_amount ?? 0) > t.reversed_amount;
  return (
    <>
      <PageHeader
        eyebrow={
          <Link to="/transactions" className="hover:text-fg">
            Transactions
          </Link>
        }
        title={
          t ? (
            <span className="flex flex-wrap items-center gap-3">
              {t.description || humanize(t.type)} <StatusBadge status={t.status} />
            </span>
          ) : (
            <Skeleton className="h-7 w-64" />
          )
        }
        description={t && <CopyId value={t.id} label="transaction id" size={36} />}
        actions={
          reversible &&
          can("money:reverse") && (
            <Button variant="danger-soft" onClick={() => setReversing(true)}>
              <RotateCcw /> Reverse
            </Button>
          )
        }
      />
      {!t ? (
        <Skeleton className="h-64 rounded-[14px]" />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="space-y-6">
            {t.status === "failed" && (
              <div role="alert" className="rounded-xl border border-danger/30 bg-danger-soft p-4 text-sm">
                <div className="font-medium text-danger">{humanize(t.failure_code)}</div>
                <div className="mt-0.5 text-fg-2">
                  {humanError(new WaltrixApiError(422, t.failure_code ?? "operation_failed", t.failure_message ?? ""))}{" "}
                  No journal entry was posted, so no money moved.
                </div>
              </div>
            )}
            {t.journal_entries.map((e) => (
              <Card key={e.id}>
                <CardHeader
                  title={
                    <Link to={`/ledger/entries/${e.id}`} className="hover:text-primary">
                      Journal entry #{e.entry_number}
                    </Link>
                  }
                  description={`${humanize(e.kind)} · ${dateTime(e.created_at)}`}
                  action={<Badge tone={e.phase === "posted" ? "success" : "warning"}>{humanize(e.phase)}</Badge>}
                />
                <EntryLines entry={e} />
              </Card>
            ))}
            {t.reversals.length > 0 && (
              <Card>
                <CardHeader title="Reversals" description="Corrections posted against this transaction" />
                <ul className="divide-y divide-border">
                  {t.reversals.map((r) => (
                    <li key={r.id}>
                      <button
                        className="flex w-full items-center justify-between gap-4 px-5 py-3 text-left hover:bg-surface-hover"
                        onClick={() => navigate(`/transactions/${r.id}`)}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm text-fg">{r.description || "Reversal"}</span>
                          <span className="text-xs text-muted">{dateTime(r.created_at)}</span>
                        </span>
                        <span className="flex items-center gap-3">
                          <StatusBadge status={r.status} />
                          <Money amount={r.amount} currency={r.currency} />
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>
          <Card className="h-fit">
            <CardHeader title="Details" />
            <dl className="divide-y divide-border text-sm">
              {(
                [
                  ["Amount", <Money key="a" amount={t.amount} currency={t.currency} className="text-fg" />],
                  ["Posted", <Money key="p" amount={t.posted_amount} currency={t.currency} />],
                  ["Reversed", <Money key="r" amount={t.reversed_amount || null} currency={t.currency} />],
                  ["Type", humanize(t.type)],
                  [
                    "From",
                    t.source_wallet_id ? (
                      <Link key="f" className="text-primary hover:underline" to={`/wallets/${t.source_wallet_id}`}>
                        {t.source_wallet_id.slice(0, 8)}
                      </Link>
                    ) : t.type === "deposit" ? (
                      "Simulated funding"
                    ) : (
                      "-"
                    ),
                  ],
                  [
                    "To",
                    t.destination_wallet_id ? (
                      <Link key="t" className="text-primary hover:underline" to={`/wallets/${t.destination_wallet_id}`}>
                        {t.destination_wallet_id.slice(0, 8)}
                      </Link>
                    ) : t.type === "withdrawal" ? (
                      "Simulated funding"
                    ) : (
                      "-"
                    ),
                  ],
                  [
                    "Original",
                    t.original_transaction_id ? (
                      <Link
                        key="o"
                        className="text-primary hover:underline"
                        to={`/transactions/${t.original_transaction_id}`}
                      >
                        {t.original_transaction_id.slice(0, 8)}
                      </Link>
                    ) : null,
                  ],
                  ["Hold", t.hold_id ? <CopyId key="h" value={t.hold_id} /> : null],
                  ["Reference", t.reference],
                  ["Actor", `${humanize(t.actor_type)}${t.actor_id ? ` · ${t.actor_id.slice(0, 8)}` : ""}`],
                  [
                    "Correlation",
                    t.correlation_id ? (
                      <span key="c" className="break-all font-mono text-xs">
                        {t.correlation_id}
                      </span>
                    ) : null,
                  ],
                  ["Created", dateTime(t.created_at)],
                  ["Posted at", dateTime(t.posted_at)],
                ] as [string, React.ReactNode][]
              )
                .filter(([, v]) => v !== null && v !== undefined)
                .map(([k, v]) => (
                  <div key={k} className="flex items-start justify-between gap-4 px-5 py-2.5">
                    <dt className="shrink-0 text-muted">{k}</dt>
                    <dd className={cn("min-w-0 text-right text-fg-2")}>{v}</dd>
                  </div>
                ))}
            </dl>
          </Card>
        </div>
      )}
      {t && reversing && <ReverseDialog tx={t} open onOpenChange={setReversing} />}
    </>
  );
}
