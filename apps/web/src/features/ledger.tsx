import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { Account, JournalEntry } from "@waltrix/sdk";
import { BookOpen } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { DataTable, ErrorState, Money, Pager, useCursorPager, type Column } from "@/components/ui/data";
import { Select, Tabs, TabsContent, TabsList } from "@/components/ui/overlays";
import { Badge, Card, CardHeader, CopyId, EmptyState, PageHeader, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dateTime, formatMoney, humanize, relative } from "@/lib/format";

import { EntryLines } from "./transactions";

const KINDS = ["transfer", "deposit", "withdrawal", "hold", "capture", "reversal", "manual"];

function EntriesTab() {
  const navigate = useNavigate();
  const pager = useCursorPager();
  const [kind, setKind] = useState("all");
  const [phase, setPhase] = useState("all");
  const q = useQuery({
    queryKey: ["journal", { kind, phase, cursor: pager.cursor }],
    queryFn: () =>
      api.journalEntries.list({
        limit: 25,
        cursor: pager.cursor,
        kind: kind === "all" ? undefined : kind,
        phase: phase === "all" ? undefined : (phase as "posted" | "pending"),
      }),
    placeholderData: keepPreviousData,
  });
  const columns: Column<JournalEntry>[] = [
    {
      key: "no",
      header: "Entry",
      primary: true,
      cell: (e) => (
        <div>
          <div className="font-medium text-fg">
            #{e.entry_number} · {e.description}
          </div>
          <div className="font-mono text-xs text-faint">{e.id.slice(0, 8)}</div>
        </div>
      ),
    },
    { key: "kind", header: "Kind", cell: (e) => <span className="text-fg-2">{humanize(e.kind)}</span> },
    {
      key: "phase",
      header: "Phase",
      cell: (e) => <Badge tone={e.phase === "posted" ? "success" : "warning"}>{humanize(e.phase)}</Badge>,
    },
    {
      key: "lines",
      header: "Lines",
      align: "right",
      hideOnMobile: true,
      cell: (e) => <span className="tabular text-muted">{e.postings.length}</span>,
    },
    {
      key: "amount",
      header: "Amount",
      align: "right",
      cell: (e) => {
        const d = e.postings.filter((p) => p.direction === "debit").reduce((s, p) => s + p.amount, 0);
        return <Money amount={d} currency={e.postings[0]?.currency ?? "USD"} />;
      },
    },
    {
      key: "when",
      header: "Created",
      align: "right",
      cell: (e) => <span className="whitespace-nowrap text-[13px] text-muted">{relative(e.created_at)}</span>,
    },
  ];
  return (
    <>
      <div className="flex flex-col gap-3 border-b border-border p-4 sm:flex-row">
        <Select
          aria-label="Kind"
          className="sm:w-44"
          value={kind}
          onValueChange={(v) => {
            setKind(v);
            pager.reset();
          }}
          options={[{ value: "all", label: "All kinds" }, ...KINDS.map((k) => ({ value: k, label: humanize(k) }))]}
        />
        <Select
          aria-label="Phase"
          className="sm:w-44"
          value={phase}
          onValueChange={(v) => {
            setPhase(v);
            pager.reset();
          }}
          options={[
            { value: "all", label: "Posted + pending" },
            { value: "posted", label: "Posted" },
            { value: "pending", label: "Pending" },
          ]}
        />
      </div>
      {q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        <DataTable
          caption="Journal entries"
          columns={columns}
          rows={q.data?.data}
          rowKey={(e) => e.id}
          onRowClick={(e) => navigate(`/ledger/entries/${e.id}`)}
          empty={<EmptyState icon={<BookOpen />} title="No journal entries" />}
        />
      )}
      <Pager
        page={pager.page}
        hasMore={q.data?.has_more ?? false}
        busy={q.isFetching}
        onPrev={pager.prev}
        onNext={() => pager.next(q.data?.next_cursor ?? null)}
      />
    </>
  );
}

function AccountsTab() {
  const pager = useCursorPager();
  const [walletsToo, setWalletsToo] = useState("internal");
  const q = useQuery({
    queryKey: ["accounts", { walletsToo, cursor: pager.cursor }],
    queryFn: () => api.accounts.list({ limit: 50, cursor: pager.cursor, include_wallets: walletsToo === "all" }),
    placeholderData: keepPreviousData,
  });
  const columns: Column<Account>[] = [
    {
      key: "name",
      header: "Account",
      primary: true,
      cell: (a) => (
        <div>
          <div className="font-medium text-fg">{a.name}</div>
          <div className="font-mono text-xs text-faint">{a.code}</div>
        </div>
      ),
    },
    { key: "type", header: "Type", cell: (a) => <span className="text-fg-2">{humanize(a.type)}</span> },
    {
      key: "normal",
      header: "Normal side",
      hideOnMobile: true,
      cell: (a) => <span className="text-muted">{humanize(a.normal_balance)}</span>,
    },
    {
      key: "flags",
      header: "Flags",
      hideOnMobile: true,
      cell: (a) => (
        <div className="flex gap-1.5">
          {a.is_system && <Badge tone="info">System</Badge>}
          {a.allow_negative && <Badge tone="warning">Negative OK</Badge>}
        </div>
      ),
    },
    {
      key: "balance",
      header: "Balance",
      align: "right",
      cell: (a) => <Money amount={a.balance.posted} currency={a.currency} className="text-fg" />,
    },
  ];
  return (
    <>
      <div className="flex border-b border-border p-4">
        <Select
          aria-label="Account scope"
          className="sm:w-56"
          value={walletsToo}
          onValueChange={(v) => {
            setWalletsToo(v);
            pager.reset();
          }}
          options={[
            { value: "internal", label: "Internal & system accounts" },
            { value: "all", label: "All accounts (incl. wallets)" },
          ]}
        />
      </div>
      {q.error ? (
        <ErrorState error={q.error} />
      ) : (
        <DataTable
          caption="Accounts"
          columns={columns}
          rows={q.data?.data}
          rowKey={(a) => a.id}
          empty={
            <EmptyState
              icon={<BookOpen />}
              title="No internal accounts yet"
              description="The simulated funding account appears after the first deposit."
            />
          }
        />
      )}
      <Pager
        page={pager.page}
        hasMore={q.data?.has_more ?? false}
        onPrev={pager.prev}
        onNext={() => pager.next(q.data?.next_cursor ?? null)}
      />
    </>
  );
}

export function LedgerPage() {
  return (
    <>
      <PageHeader
        title="Ledger"
        description="The authoritative, append-only journal. Every entry balances per currency; nothing here is ever edited."
      />
      <Card>
        <Tabs defaultValue="entries">
          <div className="px-5 pt-3">
            <TabsList
              items={[
                { value: "entries", label: "Journal entries" },
                { value: "accounts", label: "Chart of accounts" },
              ]}
            />
          </div>
          <TabsContent value="entries">
            <EntriesTab />
          </TabsContent>
          <TabsContent value="accounts">
            <AccountsTab />
          </TabsContent>
        </Tabs>
      </Card>
    </>
  );
}

export function JournalEntryPage() {
  const { id = "" } = useParams();
  const q = useQuery({ queryKey: ["journal", id], queryFn: () => api.journalEntries.get(id) });
  if (q.error)
    return (
      <Card>
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </Card>
    );
  const e = q.data;
  return (
    <>
      <PageHeader
        eyebrow={
          <Link to="/ledger" className="hover:text-fg">
            Ledger
          </Link>
        }
        title={e ? `Journal entry #${e.entry_number}` : <Skeleton className="h-7 w-56" />}
        description={
          e && (
            <span className="flex flex-wrap items-center gap-2">
              {e.description} <CopyId value={e.id} size={36} />
            </span>
          )
        }
      />
      {!e ? (
        <Skeleton className="h-64 rounded-[14px]" />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
          <Card>
            <CardHeader
              title="Postings"
              description="Debits and credits must be equal per currency (checked again by the database at commit)."
            />
            <EntryLines entry={e} />
          </Card>
          <Card className="h-fit">
            <CardHeader title="Metadata" />
            <dl className="divide-y divide-border text-sm">
              {(
                [
                  [
                    "Phase",
                    <Badge key="p" tone={e.phase === "posted" ? "success" : "warning"}>
                      {humanize(e.phase)}
                    </Badge>,
                  ],
                  ["Kind", humanize(e.kind)],
                  [
                    "Transaction",
                    e.transaction_id ? (
                      <Link key="t" className="text-primary hover:underline" to={`/transactions/${e.transaction_id}`}>
                        {e.transaction_id.slice(0, 8)}
                      </Link>
                    ) : (
                      "-"
                    ),
                  ],
                  [
                    "Reverses",
                    e.reverses_entry_id ? (
                      <Link
                        key="r"
                        className="text-primary hover:underline"
                        to={`/ledger/entries/${e.reverses_entry_id}`}
                      >
                        {e.reverses_entry_id.slice(0, 8)}
                      </Link>
                    ) : (
                      "-"
                    ),
                  ],
                  ["Actor", `${humanize(e.actor_type)}${e.actor_id ? ` · ${e.actor_id.slice(0, 8)}` : ""}`],
                  [
                    "Correlation",
                    <span key="c" className="break-all font-mono text-xs">
                      {e.correlation_id ?? "-"}
                    </span>,
                  ],
                  ["Effective", dateTime(e.effective_at)],
                  [
                    "Total",
                    formatMoney(
                      e.postings.filter((p) => p.direction === "debit").reduce((s, p) => s + p.amount, 0),
                      e.postings[0]?.currency ?? "USD",
                    ),
                  ],
                ] as [string, React.ReactNode][]
              ).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between gap-4 px-5 py-2.5">
                  <dt className="text-muted">{k}</dt>
                  <dd className="text-right text-fg-2">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </div>
      )}
    </>
  );
}
