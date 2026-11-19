import { useQuery } from "@tanstack/react-query";
import type { Overview, Transaction } from "@waltrix/sdk";
import {
  Activity,
  AlertOctagon,
  ArrowLeftRight,
  CheckCircle2,
  Clock,
  Lock,
  Send,
  ShieldAlert,
  Wallet,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { DataTable, ErrorState, Money, StatusBadge, type Column } from "@/components/ui/data";
import { Select } from "@/components/ui/overlays";
import { Badge, Button, Card, CardHeader, EmptyState, PageHeader, Skeleton, Stat } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { compactMoney, formatMoney, humanize, relative, shortDate } from "@/lib/format";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

const STATUS_COLORS: Record<string, string> = {
  posted: "var(--success)",
  reversed: "var(--muted)",
  pending: "var(--warning)",
  failed: "var(--danger)",
  created: "var(--info)",
};

/** Transaction columns. With `walletId`, amounts are signed relative to that wallet (+ in, − out). */
export function txColumns(walletId?: string): Column<Transaction>[] {
  const sign = (t: Transaction): "in" | "out" | undefined => {
    if (!walletId || t.status === "failed") return undefined;
    if (t.type === "hold" && t.status === "pending") return undefined;
    return t.destination_wallet_id === walletId ? "in" : t.source_wallet_id === walletId ? "out" : undefined;
  };
  return [
    {
      key: "desc",
      header: "Transaction",
      primary: true,
      cell: (t) => (
        <div className="min-w-0">
          <div className="truncate font-medium text-fg">{t.description || humanize(t.type)}</div>
          <div className="font-mono text-xs text-faint">{t.id.slice(0, 8)}</div>
        </div>
      ),
    },
    { key: "type", header: "Type", cell: (t) => <span className="text-fg-2">{humanize(t.type)}</span> },
    { key: "status", header: "Status", cell: (t) => <StatusBadge status={t.status} /> },
    {
      key: "amount",
      header: "Amount",
      align: "right",
      cell: (t) => <Money amount={t.posted_amount ?? t.amount} currency={t.currency} signed={sign(t)} />,
    },
    {
      key: "when",
      header: "Created",
      align: "right",
      cell: (t) => <span className="whitespace-nowrap text-[13px] text-muted">{relative(t.created_at)}</span>,
    },
  ];
}

function VolumeChart({ overview }: { overview: Overview }) {
  const currencies = [...new Set(overview.volume.map((v) => v.currency))];
  const [currency, setCurrency] = useState<string | undefined>(undefined);
  const active = currency ?? currencies[0];
  const data = useMemo(() => {
    // Fill missing days with zeros so the chart does not lie about continuity.
    const byDay = new Map(overview.volume.filter((v) => v.currency === active).map((v) => [v.day, v]));
    const out = [];
    for (let i = overview.window_days - 1; i >= 0; i--) {
      const d = new Date();
      d.setUTCHours(0, 0, 0, 0);
      d.setUTCDate(d.getUTCDate() - i);
      const key = d.toISOString().slice(0, 10);
      const row = byDay.get(key);
      out.push({ day: key, amount: row?.amount ?? 0, count: row?.count ?? 0 });
    }
    return out;
  }, [overview, active]);

  return (
    <Card className="lg:col-span-2">
      <CardHeader
        title="Posted volume"
        description={`Last ${overview.window_days} days · reversals excluded`}
        action={
          currencies.length > 1 ? (
            <Select
              aria-label="Chart currency"
              className="h-8 w-24"
              value={active}
              onValueChange={setCurrency}
              options={currencies.map((c) => ({ value: c, label: c }))}
            />
          ) : undefined
        }
      />
      <div className="h-64 px-2 pb-3 pt-4">
        {!active ? (
          <EmptyState
            icon={<Activity />}
            title="No posted volume yet"
            description="Volume appears after the first posted transaction."
          />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ left: 8, right: 16, top: 8 }}>
              <defs>
                <linearGradient id="vol" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 4" />
              <XAxis
                dataKey="day"
                tickFormatter={(d: string) => shortDate(`${d}T00:00:00Z`)}
                tick={{ fill: "var(--faint)", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                minTickGap={28}
              />
              <YAxis
                tickFormatter={(v: number) => compactMoney(v, active)}
                tick={{ fill: "var(--faint)", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={64}
              />
              <Tooltip
                cursor={{ stroke: "var(--border-strong)" }}
                contentStyle={{
                  background: "var(--surface-2)",
                  border: "1px solid var(--border)",
                  borderRadius: 10,
                  fontSize: 12,
                  color: "var(--text)",
                }}
                labelFormatter={(d) => shortDate(`${String(d)}T00:00:00Z`)}
                formatter={(v, _n, item) => [
                  `${formatMoney(Number(v), active)} · ${(item.payload as { count: number }).count} tx`,
                  "Volume",
                ]}
              />
              <Area
                type="monotone"
                dataKey="amount"
                stroke="var(--chart-1)"
                strokeWidth={2}
                fill="url(#vol)"
                animationDuration={500}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </Card>
  );
}

function StatusDistribution({ counts }: { counts: Overview["transaction_counts"] }) {
  const entries = Object.entries(counts).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0));
  const total = entries.reduce((s, [, n]) => s + (n ?? 0), 0);
  return (
    <Card>
      <CardHeader title="Status distribution" description={`${total.toLocaleString()} transactions`} />
      <div className="space-y-4 p-5">
        <div
          className="flex h-2.5 overflow-hidden rounded-full bg-surface-2"
          role="img"
          aria-label="Transaction status distribution"
        >
          {entries.map(([s, n]) => (
            <div key={s} style={{ width: `${((n ?? 0) / Math.max(total, 1)) * 100}%`, background: STATUS_COLORS[s] }} />
          ))}
        </div>
        <ul className="space-y-2.5">
          {entries.map(([s, n]) => (
            <li key={s} className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 text-fg-2">
                <span className="size-2 rounded-full" style={{ background: STATUS_COLORS[s] }} />
                {humanize(s)}
              </span>
              <span className="tabular text-muted">
                {(n ?? 0).toLocaleString()}{" "}
                <span className="text-faint">({total ? Math.round(((n ?? 0) / total) * 100) : 0}%)</span>
              </span>
            </li>
          ))}
          {entries.length === 0 && <li className="text-sm text-muted">No transactions yet.</li>}
        </ul>
      </div>
    </Card>
  );
}

export function OverviewPage() {
  const { membership, can } = useSession();
  const navigate = useNavigate();
  const overview = useQuery({ queryKey: ["overview"], queryFn: () => api.overview.get(30) });
  const recent = useQuery({ queryKey: ["transactions", "recent"], queryFn: () => api.transactions.list({ limit: 8 }) });
  const o = overview.data;
  const totalTx = o ? Object.values(o.transaction_counts).reduce((s, n) => s + (n ?? 0), 0) : 0;
  const recon = o?.last_reconciliation;

  return (
    <>
      <PageHeader
        eyebrow={membership?.organization.name}
        title="Overview"
        description="Live figures computed from the journal. Nothing on this page is estimated."
        actions={
          can("money:move") && (
            <Button variant="primary" onClick={() => navigate("/transfer")}>
              <Send /> New transfer
            </Button>
          )
        }
      />
      {overview.error ? (
        <Card>
          <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
        </Card>
      ) : (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {!o ? (
              Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[118px] rounded-[14px]" />)
            ) : (
              <>
                <Card className="p-5 sm:col-span-2 xl:col-span-1">
                  <div className="flex items-center justify-between">
                    <span className="text-[13px] font-medium text-muted">Wallet balances</span>
                    <span className="grid size-8 place-items-center rounded-lg bg-primary-soft text-primary">
                      <Wallet className="size-4" />
                    </span>
                  </div>
                  <ul className="mt-3 space-y-1.5">
                    {o.balances.map((b) => (
                      <li key={b.currency} className="flex items-baseline justify-between gap-3">
                        <span className="tabular text-xl font-semibold tracking-tight text-fg">
                          {formatMoney(b.total_posted, b.currency)}
                        </span>
                        <span className="text-xs text-muted">{b.wallet_count} wallets</span>
                      </li>
                    ))}
                    {o.balances.length === 0 && <li className="text-sm text-muted">No wallets yet</li>}
                  </ul>
                </Card>
                <Stat
                  label="Transactions"
                  value={totalTx.toLocaleString()}
                  icon={<ArrowLeftRight />}
                  sub="All time, all statuses"
                />
                <Stat
                  label="Active holds"
                  value={o.active_holds.reduce((s, h) => s + h.count, 0).toLocaleString()}
                  icon={<Lock />}
                  sub={o.active_holds.map((h) => formatMoney(h.amount, h.currency)).join(" · ") || "Nothing reserved"}
                />
                <Stat
                  label="Failed (24h)"
                  value={o.failed_last_24h.toLocaleString()}
                  icon={<AlertOctagon />}
                  tone={o.failed_last_24h ? "danger" : undefined}
                  sub={
                    o.failed_last_24h ? (
                      <Link to="/transactions?status=failed" className="text-danger hover:underline">
                        Review failed operations
                      </Link>
                    ) : (
                      "No failures in the last day"
                    )
                  }
                />
              </>
            )}
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            {o ? <VolumeChart overview={o} /> : <Skeleton className="h-[330px] rounded-[14px] lg:col-span-2" />}
            {o ? (
              <StatusDistribution counts={o.transaction_counts} />
            ) : (
              <Skeleton className="h-[330px] rounded-[14px]" />
            )}
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader
                title="Recent activity"
                action={
                  <Button variant="ghost" size="sm" onClick={() => navigate("/transactions")}>
                    View all
                  </Button>
                }
              />
              {recent.error ? (
                <ErrorState error={recent.error} onRetry={() => void recent.refetch()} />
              ) : (
                <DataTable
                  caption="Recent transactions"
                  columns={txColumns()}
                  rows={recent.data?.data}
                  rowKey={(t) => t.id}
                  onRowClick={(t) => navigate(`/transactions/${t.id}`)}
                  empty={
                    <EmptyState
                      icon={<ArrowLeftRight />}
                      title="No transactions yet"
                      description="Fund a wallet to get started."
                    />
                  }
                />
              )}
            </Card>
            <Card>
              <CardHeader title="Reconciliation" description="Journal vs. materialized balances" />
              <div className="p-5">
                {!o ? (
                  <Skeleton className="h-24" />
                ) : !recon ? (
                  <EmptyState
                    icon={<ShieldAlert />}
                    title="Never reconciled"
                    description="Run a reconciliation to verify every balance against the journal."
                    action={
                      <Button size="sm" onClick={() => navigate("/reconciliation")}>
                        Open reconciliation
                      </Button>
                    }
                  />
                ) : (
                  <div className="space-y-4">
                    <div
                      className={cn(
                        "flex items-center gap-3 rounded-xl border p-4",
                        recon.status === "passed"
                          ? "border-success/25 bg-success-soft"
                          : "border-danger/30 bg-danger-soft",
                      )}
                    >
                      {recon.status === "passed" ? (
                        <CheckCircle2 className="size-6 text-success" />
                      ) : (
                        <AlertOctagon className="size-6 text-danger" />
                      )}
                      <div>
                        <div className="text-sm font-semibold text-fg">
                          {recon.status === "passed" ? "All checks passed" : `${recon.summary.errors} issue(s) found`}
                        </div>
                        <div className="flex items-center gap-1 text-xs text-muted">
                          <Clock className="size-3" /> {relative(recon.created_at)} · {recon.duration_ms} ms
                        </div>
                      </div>
                    </div>
                    <dl className="grid grid-cols-2 gap-3 text-[13px]">
                      <div>
                        <dt className="text-faint">Checks</dt>
                        <dd className="tabular text-fg">{Object.keys(recon.summary.checks).length}</dd>
                      </div>
                      <div>
                        <dt className="text-faint">Warnings</dt>
                        <dd className="tabular text-fg">{recon.summary.warnings}</dd>
                      </div>
                      <div>
                        <dt className="text-faint">Journal entries</dt>
                        <dd className="tabular text-fg">{recon.summary.counts["entries"]?.toLocaleString()}</dd>
                      </div>
                      <div>
                        <dt className="text-faint">Postings</dt>
                        <dd className="tabular text-fg">{recon.summary.counts["postings"]?.toLocaleString()}</dd>
                      </div>
                    </dl>
                    <Button size="sm" className="w-full" onClick={() => navigate("/reconciliation")}>
                      Details
                    </Button>
                  </div>
                )}
              </div>
            </Card>
          </div>
          <p className="flex items-center gap-2 text-xs text-faint">
            <Badge tone="warning">Simulated funding</Badge>
            Deposits and withdrawals use a synthetic funding account. No real bank settlement occurs.
          </p>
        </div>
      )}
    </>
  );
}
