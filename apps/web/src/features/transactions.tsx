import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  WaltrixApiError,
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
import { dateTime, formatMoney, humanize, parseAmount } from "@/lib/format";
import { msg, t } from "@/lib/i18n";
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
        title={t("Transactions")}
        description={t("Every operation requested, including failed ones. Money movement itself lives in the ledger.")}
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
            <Search className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
            <Input
              aria-label={t("Search transactions")}
              className="ps-9"
              placeholder={t("Search by id, reference or description - press Enter")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </form>
          <Select
            aria-label={t("Status")}
            className="lg:w-40"
            value={status}
            onValueChange={(v) => set("status", v)}
            options={[
              { value: "all", label: t("All statuses") },
              ...STATUSES.map((s) => ({ value: s, label: humanize(s) })),
            ]}
          />
          <Select
            aria-label={t("Type")}
            className="lg:w-40"
            value={type}
            onValueChange={(v) => set("type", v)}
            options={[
              { value: "all", label: t("All types") },
              ...TYPES.map((tx) => ({ value: tx, label: humanize(tx) })),
            ]}
          />
          <Select
            aria-label={t("Sort")}
            className="lg:w-40"
            value={sort}
            onValueChange={(v) => {
              setSort(v as typeof sort);
              pager.reset();
            }}
            options={[
              { value: "-created_at", label: t("Newest first") },
              { value: "created_at", label: t("Oldest first") },
            ]}
          />
        </div>
        {query.error ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : (
          <DataTable
            caption={t("Transactions")}
            columns={txColumns()}
            rows={query.data?.data}
            rowKey={(tx) => tx.id}
            onRowClick={(tx) => navigate(`/transactions/${tx.id}`)}
            empty={
              <EmptyState
                icon={<ArrowLeftRight />}
                title={t("No transactions match")}
                description={t("Adjust the filters or search term.")}
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
        <caption className="sr-only">{t("Postings of entry {number}", { number: entry.entry_number })}</caption>
        <thead>
          <tr className="border-b border-border text-start text-xs uppercase tracking-wide text-faint">
            <th scope="col" className="px-5 py-2 font-medium">
              {t("Account")}
            </th>
            <th scope="col" className="px-5 py-2 text-end font-medium">
              {t("Debit")}
            </th>
            <th scope="col" className="px-5 py-2 text-end font-medium">
              {t("Credit")}
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
              <td className="px-5 py-2.5 text-end">
                {p.direction === "debit" ? <Money amount={p.amount} currency={p.currency} /> : ""}
              </td>
              <td className="px-5 py-2.5 text-end">
                {p.direction === "credit" ? <Money amount={p.amount} currency={p.currency} /> : ""}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="text-[13px]">
            <td className="px-5 py-2.5 text-muted">
              {t("Totals")}{" "}
              {debits === credits ? (
                <Badge tone="success" className="ms-2">
                  {t("Balanced")}
                </Badge>
              ) : (
                <Badge tone="danger" className="ms-2">
                  {t("Unbalanced")}
                </Badge>
              )}
            </td>
            <td className="tabular px-5 py-2.5 text-end font-semibold text-fg">{formatMoney(debits, currency)}</td>
            <td className="tabular px-5 py-2.5 text-end font-semibold text-fg">{formatMoney(credits, currency)}</td>
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
      title={t("Reverse transaction")}
      description={t("Posts an opposite entry. The original stays in the journal. Up to {amount} can be reversed.", {
        amount: formatMoney(remaining, tx.currency),
      })}
    >
      <form
        className="space-y-4"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          const minor = amount.trim() ? parseAmount(amount, tx.currency) : remaining;
          if (minor === null || minor <= 0) return setError(t("Enter a positive amount"));
          if (minor > remaining)
            return setError(t("At most {amount}", { amount: formatMoney(remaining, tx.currency) }));
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
          label={t("Amount ({currency})", { currency: tx.currency })}
          htmlFor="rev-amount"
          error={error ?? undefined}
          hint={t("Leave empty for a full reversal.")}
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
        <Field label={t("Reason")} htmlFor="rev-reason">
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
          success={t("Reversal posted.")}
        />
        <div className="flex justify-end gap-2">
          <Button type="button" onClick={() => close(false)} disabled={action.pending}>
            {done ? t("Close") : t("Cancel")}
          </Button>
          {!done && (
            <Button type="submit" variant="danger" loading={action.pending}>
              {action.status === "unknown" ? t("Retry safely") : t("Post reversal")}
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
  const tx = q.data;
  const reversible =
    tx && tx.status === "posted" && tx.type !== "reversal" && (tx.posted_amount ?? 0) > tx.reversed_amount;
  return (
    <>
      <PageHeader
        eyebrow={
          <Link to="/transactions" className="hover:text-fg">
            {t("Transactions")}
          </Link>
        }
        title={
          tx ? (
            <span className="flex flex-wrap items-center gap-3">
              {tx.description || humanize(tx.type)} <StatusBadge status={tx.status} />
            </span>
          ) : (
            <Skeleton className="h-7 w-64" />
          )
        }
        description={tx && <CopyId value={tx.id} label={t("transaction id")} size={36} />}
        actions={
          reversible &&
          can("money:reverse") && (
            <Button variant="danger-soft" onClick={() => setReversing(true)}>
              <RotateCcw /> {t("Reverse")}
            </Button>
          )
        }
      />
      {!tx ? (
        <Skeleton className="h-64 rounded-[14px]" />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="space-y-6">
            {tx.status === "failed" && (
              <div role="alert" className="rounded-xl border border-danger/30 bg-danger-soft p-4 text-sm">
                <div className="font-medium text-danger">{humanize(tx.failure_code)}</div>
                <div className="mt-0.5 text-fg-2">
                  {humanError(
                    new WaltrixApiError(422, tx.failure_code ?? "operation_failed", tx.failure_message ?? ""),
                  )}{" "}
                  {t("No journal entry was posted, so no money moved.")}
                </div>
              </div>
            )}
            {tx.journal_entries.map((e) => (
              <Card key={e.id}>
                <CardHeader
                  title={
                    <Link to={`/ledger/entries/${e.id}`} className="hover:text-primary">
                      {t("Journal entry #{number}", { number: e.entry_number })}
                    </Link>
                  }
                  description={`${humanize(e.kind)} · ${dateTime(e.created_at)}`}
                  action={<Badge tone={e.phase === "posted" ? "success" : "warning"}>{humanize(e.phase)}</Badge>}
                />
                <EntryLines entry={e} />
              </Card>
            ))}
            {tx.reversals.length > 0 && (
              <Card>
                <CardHeader title={t("Reversals")} description={t("Corrections posted against this transaction")} />
                <ul className="divide-y divide-border">
                  {tx.reversals.map((r) => (
                    <li key={r.id}>
                      <button
                        className="flex w-full items-center justify-between gap-4 px-5 py-3 text-start hover:bg-surface-hover"
                        onClick={() => navigate(`/transactions/${r.id}`)}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm text-fg">{r.description || t("Reversal")}</span>
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
            <CardHeader title={t("Details")} />
            <dl className="divide-y divide-border text-sm">
              {(
                [
                  [msg("Amount"), <Money key="a" amount={tx.amount} currency={tx.currency} className="text-fg" />],
                  [msg("Posted"), <Money key="p" amount={tx.posted_amount} currency={tx.currency} />],
                  [msg("Reversed"), <Money key="r" amount={tx.reversed_amount || null} currency={tx.currency} />],
                  [msg("Type"), humanize(tx.type)],
                  [
                    msg("From"),
                    tx.source_wallet_id ? (
                      <Link key="f" className="text-primary hover:underline" to={`/wallets/${tx.source_wallet_id}`}>
                        {tx.source_wallet_id.slice(0, 8)}
                      </Link>
                    ) : tx.type === "deposit" ? (
                      t("Simulated funding")
                    ) : (
                      "-"
                    ),
                  ],
                  [
                    msg("To"),
                    tx.destination_wallet_id ? (
                      <Link
                        key="t"
                        className="text-primary hover:underline"
                        to={`/wallets/${tx.destination_wallet_id}`}
                      >
                        {tx.destination_wallet_id.slice(0, 8)}
                      </Link>
                    ) : tx.type === "withdrawal" ? (
                      t("Simulated funding")
                    ) : (
                      "-"
                    ),
                  ],
                  [
                    msg("Original"),
                    tx.original_transaction_id ? (
                      <Link
                        key="o"
                        className="text-primary hover:underline"
                        to={`/transactions/${tx.original_transaction_id}`}
                      >
                        {tx.original_transaction_id.slice(0, 8)}
                      </Link>
                    ) : null,
                  ],
                  [msg("Hold"), tx.hold_id ? <CopyId key="h" value={tx.hold_id} /> : null],
                  [msg("Reference"), tx.reference],
                  [msg("Actor"), `${humanize(tx.actor_type)}${tx.actor_id ? ` · ${tx.actor_id.slice(0, 8)}` : ""}`],
                  [
                    msg("Correlation"),
                    tx.correlation_id ? (
                      <span key="c" className="break-all font-mono text-xs">
                        {tx.correlation_id}
                      </span>
                    ) : null,
                  ],
                  [msg("Created"), dateTime(tx.created_at)],
                  [msg("Posted at"), dateTime(tx.posted_at)],
                ] as [string, React.ReactNode][]
              )
                .filter(([, v]) => v !== null && v !== undefined)
                .map(([k, v]) => (
                  <div key={k} className="flex items-start justify-between gap-4 px-5 py-2.5">
                    <dt className="shrink-0 text-muted">{t(k)}</dt>
                    <dd className={cn("min-w-0 text-end text-fg-2")}>{v}</dd>
                  </div>
                ))}
            </dl>
          </Card>
        </div>
      )}
      {tx && reversing && <ReverseDialog tx={tx} open onOpenChange={setReversing} />}
    </>
  );
}
