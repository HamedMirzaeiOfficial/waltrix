import { zodResolver } from "@hookform/resolvers/zod";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { parseMoney, type Hold, type StatementLine, type Wallet } from "@waltrix/sdk";
import {
  ArrowDownLeft,
  ArrowUpRight,
  Ban,
  Lock,
  Pause,
  Play,
  Plus,
  Search,
  Send,
  Wallet as WalletIcon,
} from "lucide-react";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router-dom";
import { z } from "zod";

import { ActionResult } from "@/components/ActionResult";
import { DataTable, ErrorState, Money, Pager, StatusBadge, useCursorPager, type Column } from "@/components/ui/data";
import { ConfirmDialog, Dialog, Select, Tabs, TabsContent, TabsList } from "@/components/ui/overlays";
import {
  Badge,
  Button,
  Card,
  CopyId,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Skeleton,
} from "@/components/ui/primitives";
import { toast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { humanError } from "@/lib/errors";
import { dateTime, formatMoney, humanize, relative } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useIdempotentAction } from "@/lib/useIdempotentAction";

import { txColumns } from "./overview";

const CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "AED", "IRR", "KRW"];

const createSchema = z.object({
  name: z.string().trim().min(1, "Name is required").max(120),
  owner_reference: z
    .string()
    .trim()
    .min(1, "Owner reference is required")
    .max(120)
    .regex(/^[\w.:@-]+$/, "Letters, digits and . _ : @ - only"),
  currency: z.string().length(3),
});

function CreateWalletDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const form = useForm<z.infer<typeof createSchema>>({
    resolver: zodResolver(createSchema),
    defaultValues: { name: "", owner_reference: "", currency: "USD" },
  });
  const create = useMutation({
    mutationFn: (v: z.infer<typeof createSchema>) => api.wallets.create(v),
    onSuccess: (w) => {
      void qc.invalidateQueries({ queryKey: ["wallets"] });
      toast("success", "Wallet created", `${w.name} (${w.currency})`);
      onOpenChange(false);
      form.reset();
      navigate(`/wallets/${w.id}`);
    },
  });
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Create wallet"
      description="A wallet is backed by its own liability account in the ledger."
    >
      <form className="space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
        <Field label="Display name" htmlFor="w-name" error={form.formState.errors.name?.message}>
          <Input id="w-name" {...form.register("name")} />
        </Field>
        <Field
          label="Owner reference"
          htmlFor="w-owner"
          error={form.formState.errors.owner_reference?.message}
          hint="Your customer id in your own system, e.g. cust_1042."
        >
          <Input id="w-owner" className="font-mono" {...form.register("owner_reference")} />
        </Field>
        <Field label="Currency" htmlFor="w-currency" hint="A wallet holds exactly one currency, forever.">
          <Controller
            control={form.control}
            name="currency"
            render={({ field }) => (
              <Select
                id="w-currency"
                value={field.value}
                onValueChange={field.onChange}
                options={CURRENCIES.map((c) => ({ value: c, label: c }))}
              />
            )}
          />
        </Field>
        {create.error && (
          <p role="alert" className="text-sm text-danger">
            {humanError(create.error)}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={create.isPending}>
            Create wallet
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function WalletsPage() {
  const navigate = useNavigate();
  const { can } = useSession();
  const pager = useCursorPager();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [currency, setCurrency] = useState("all");
  const [creating, setCreating] = useState(false);
  const query = useQuery({
    queryKey: ["wallets", { cursor: pager.cursor, search, status, currency }],
    queryFn: () =>
      api.wallets.list({
        limit: 20,
        cursor: pager.cursor,
        search: search || undefined,
        status: status === "all" ? undefined : (status as Wallet["status"]),
        currency: currency === "all" ? undefined : currency,
      }),
    placeholderData: keepPreviousData,
  });
  const columns: Column<Wallet>[] = [
    {
      key: "name",
      header: "Wallet",
      primary: true,
      cell: (w) => (
        <div className="flex items-center gap-3">
          <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-2 text-xs font-semibold text-fg-2">
            {w.name.charAt(0)}
          </span>
          <div className="min-w-0">
            <div className="truncate font-medium text-fg">{w.name}</div>
            <div className="truncate font-mono text-xs text-faint">{w.owner_reference}</div>
          </div>
        </div>
      ),
    },
    { key: "status", header: "Status", cell: (w) => <StatusBadge status={w.status} /> },
    {
      key: "currency",
      header: "Currency",
      cell: (w) => <span className="font-mono text-xs text-fg-2">{w.currency}</span>,
    },
    {
      key: "held",
      header: "On hold",
      align: "right",
      hideOnMobile: true,
      cell: (w) =>
        w.balance.pending_outgoing ? (
          <Money amount={w.balance.pending_outgoing} currency={w.currency} className="text-warning" />
        ) : (
          <span className="text-faint">-</span>
        ),
    },
    {
      key: "available",
      header: "Available",
      align: "right",
      cell: (w) => <Money amount={w.balance.available} currency={w.currency} />,
    },
    {
      key: "posted",
      header: "Balance",
      align: "right",
      cell: (w) => <Money amount={w.balance.posted} currency={w.currency} className="text-fg" />,
    },
  ];
  return (
    <>
      <PageHeader
        title="Wallets"
        description="Customer-facing balances. Each wallet is a view over a ledger account; balances come from the journal."
        actions={
          can("wallets:manage") && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <Plus /> New wallet
            </Button>
          )
        }
      />
      <Card>
        <div className="flex flex-col gap-3 border-b border-border p-4 sm:flex-row">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
            <Input
              aria-label="Search wallets"
              placeholder="Search name or owner reference"
              className="pl-9"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                pager.reset();
              }}
            />
          </div>
          <Select
            aria-label="Status filter"
            className="sm:w-40"
            value={status}
            onValueChange={(v) => {
              setStatus(v);
              pager.reset();
            }}
            options={[
              { value: "all", label: "All statuses" },
              ...["active", "suspended", "closed"].map((s) => ({ value: s, label: humanize(s) })),
            ]}
          />
          <Select
            aria-label="Currency filter"
            className="sm:w-36"
            value={currency}
            onValueChange={(v) => {
              setCurrency(v);
              pager.reset();
            }}
            options={[{ value: "all", label: "All currencies" }, ...CURRENCIES.map((c) => ({ value: c, label: c }))]}
          />
        </div>
        {query.error ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : (
          <DataTable
            caption="Wallets"
            columns={columns}
            rows={query.data?.data}
            rowKey={(w) => w.id}
            onRowClick={(w) => navigate(`/wallets/${w.id}`)}
            empty={
              <EmptyState
                icon={<WalletIcon />}
                title={search ? "No matching wallets" : "No wallets yet"}
                description={
                  search ? "Try another search term." : "Create a wallet for each customer balance you hold."
                }
                action={
                  !search && can("wallets:manage") ? (
                    <Button variant="primary" onClick={() => setCreating(true)}>
                      <Plus /> New wallet
                    </Button>
                  ) : undefined
                }
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
      <CreateWalletDialog open={creating} onOpenChange={setCreating} />
    </>
  );
}

// --- wallet detail -------------------------------------------------------------------

function FundingDialog({
  wallet,
  kind,
  open,
  onOpenChange,
}: {
  wallet: Wallet;
  kind: "credit" | "debit";
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const action = useIdempotentAction<unknown>();
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const close = (o: boolean) => {
    if (action.pending) return;
    onOpenChange(o);
    if (!o) {
      action.reset();
      setAmount("");
      setDescription("");
      setError(null);
    }
  };
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const minor = parseMoney(amount, wallet.currency);
    if (minor === null || minor <= 0) return setError(`Enter a positive ${wallet.currency} amount`);
    if (kind === "debit" && minor > wallet.balance.available) return setError("Exceeds the available balance");
    setError(null);
    void action.run((key) =>
      api.wallets[kind](
        wallet.id,
        { amount: minor, currency: wallet.currency, description: description || undefined },
        { idempotencyKey: key },
      ),
    );
  };
  const done = action.status === "success" || action.status === "failed";
  return (
    <Dialog
      open={open}
      onOpenChange={close}
      title={kind === "credit" ? "Add funds (simulated)" : "Withdraw funds (simulated)"}
      description={
        <span>
          <Badge tone="warning">Synthetic</Badge> Uses the simulated funding source. No real bank transfer happens.
        </span>
      }
    >
      <form className="space-y-4" onSubmit={submit} noValidate>
        <Field
          label={`Amount (${wallet.currency})`}
          htmlFor="fund-amount"
          error={error ?? undefined}
          hint={kind === "debit" ? `Available: ${formatMoney(wallet.balance.available, wallet.currency)}` : undefined}
        >
          <Input
            id="fund-amount"
            inputMode="decimal"
            className="tabular"
            value={amount}
            disabled={action.pending || done}
            onChange={(e) => {
              setAmount(e.target.value);
              if (action.status !== "idle" && action.status !== "unknown") action.reset();
            }}
          />
        </Field>
        <Field label="Description (optional)" htmlFor="fund-desc">
          <Input
            id="fund-desc"
            value={description}
            disabled={action.pending || done}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        <ActionResult
          status={action.status}
          message={action.message}
          failedTransactionId={action.failedTransactionId}
          success={`${kind === "credit" ? "Credited" : "Debited"} ${amount} ${wallet.currency}.`}
        />
        <div className="flex justify-end gap-2">
          <Button type="button" onClick={() => close(false)} disabled={action.pending}>
            {done ? "Close" : "Cancel"}
          </Button>
          {!done && (
            <Button type="submit" variant="primary" loading={action.pending}>
              {action.status === "unknown" ? "Retry safely" : kind === "credit" ? "Add funds" : "Withdraw"}
            </Button>
          )}
        </div>
      </form>
    </Dialog>
  );
}

function HoldDialog({
  wallet,
  open,
  onOpenChange,
}: {
  wallet: Wallet;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const action = useIdempotentAction<Hold>();
  const [amount, setAmount] = useState("");
  const [dest, setDest] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const others = useQuery({
    queryKey: ["wallets", "hold-dest", wallet.currency],
    queryFn: () => api.wallets.list({ limit: 100, status: "active", currency: wallet.currency }),
    enabled: open,
  });
  const close = (o: boolean) => {
    if (action.pending) return;
    onOpenChange(o);
    if (!o) {
      action.reset();
      setAmount("");
      setDest(undefined);
      setError(null);
    }
  };
  const done = action.status === "success" || action.status === "failed";
  return (
    <Dialog
      open={open}
      onOpenChange={close}
      title="Reserve funds"
      description="A hold moves funds to pending. Capture posts it; release returns it."
    >
      <form
        className="space-y-4"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          const minor = parseMoney(amount, wallet.currency);
          if (!dest) return setError("Choose a destination wallet");
          if (minor === null || minor <= 0) return setError(`Enter a positive ${wallet.currency} amount`);
          setError(null);
          void action.run((key) =>
            api.holds.create(
              { wallet_id: wallet.id, destination_wallet_id: dest, amount: minor, currency: wallet.currency },
              { idempotencyKey: key },
            ),
          );
        }}
      >
        <Field label="Beneficiary wallet" htmlFor="hold-dest">
          <Select
            id="hold-dest"
            value={dest}
            onValueChange={setDest}
            placeholder="Select wallet"
            options={(others.data?.data ?? [])
              .filter((w) => w.id !== wallet.id)
              .map((w) => ({ value: w.id, label: w.name, hint: w.owner_reference }))}
          />
        </Field>
        <Field
          label={`Amount (${wallet.currency})`}
          htmlFor="hold-amount"
          error={error ?? undefined}
          hint={`Available: ${formatMoney(wallet.balance.available, wallet.currency)}`}
        >
          <Input
            id="hold-amount"
            inputMode="decimal"
            className="tabular"
            value={amount}
            disabled={action.pending || done}
            onChange={(e) => setAmount(e.target.value)}
          />
        </Field>
        <ActionResult
          status={action.status}
          message={action.message}
          failedTransactionId={action.failedTransactionId}
          success="Funds reserved. The hold expires in 7 days unless captured or released."
        />
        <div className="flex justify-end gap-2">
          <Button type="button" onClick={() => close(false)} disabled={action.pending}>
            {done ? "Close" : "Cancel"}
          </Button>
          {!done && (
            <Button type="submit" variant="primary" loading={action.pending}>
              {action.status === "unknown" ? "Retry safely" : "Reserve"}
            </Button>
          )}
        </div>
      </form>
    </Dialog>
  );
}

function HoldsPanel({ wallet }: { wallet: Wallet }) {
  const { can } = useSession();
  const holds = useQuery({
    queryKey: ["holds", wallet.id],
    queryFn: () => api.holds.list({ wallet_id: wallet.id, limit: 50 }),
  });
  const capture = useIdempotentAction<Hold>();
  const release = useIdempotentAction<Hold>();
  const [target, setTarget] = useState<{ hold: Hold; kind: "capture" | "release" } | null>(null);
  const act = target?.kind === "capture" ? capture : release;
  const columns: Column<Hold>[] = [
    {
      key: "id",
      header: "Hold",
      primary: true,
      cell: (h) => (
        <div>
          <div className="font-medium text-fg">
            {h.description || (h.wallet_id === wallet.id ? "Outgoing hold" : "Incoming hold")}
          </div>
          <CopyId value={h.id} />
        </div>
      ),
    },
    { key: "status", header: "Status", cell: (h) => <StatusBadge status={h.status} /> },
    { key: "amount", header: "Amount", align: "right", cell: (h) => <Money amount={h.amount} currency={h.currency} /> },
    {
      key: "captured",
      header: "Captured",
      align: "right",
      cell: (h) => <Money amount={h.captured_amount} currency={h.currency} />,
    },
    {
      key: "expires",
      header: "Expires",
      align: "right",
      cell: (h) => (
        <span className="text-[13px] text-muted">{h.status === "active" ? relative(h.expires_at) : "-"}</span>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      hideOnMobile: false,
      cell: (h) =>
        h.status === "active" && can("money:move") && h.wallet_id === wallet.id ? (
          <div className="flex justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
            <Button
              size="sm"
              onClick={() => {
                capture.reset();
                setTarget({ hold: h, kind: "capture" });
              }}
            >
              Capture
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                release.reset();
                setTarget({ hold: h, kind: "release" });
              }}
            >
              Release
            </Button>
          </div>
        ) : null,
    },
  ];
  return (
    <>
      <DataTable
        caption="Holds"
        columns={columns}
        rows={holds.data?.data}
        rowKey={(h) => h.id}
        empty={<EmptyState icon={<Lock />} title="No holds" description="Reserved funds will appear here." />}
      />
      {target && (
        <ConfirmDialog
          open
          onOpenChange={(o) => !o && setTarget(null)}
          title={target.kind === "capture" ? "Capture full hold?" : "Release hold?"}
          description={
            target.kind === "capture"
              ? `Posts ${formatMoney(target.hold.amount, target.hold.currency)} to the beneficiary. This is final.`
              : `Returns ${formatMoney(target.hold.amount, target.hold.currency)} to the available balance.`
          }
          confirmLabel={act.status === "unknown" ? "Retry safely" : target.kind === "capture" ? "Capture" : "Release"}
          loading={act.pending}
          onConfirm={async () => {
            if (act.status === "success" || act.status === "failed") return setTarget(null);
            const res = await act.run((key) =>
              target.kind === "capture"
                ? api.holds.capture(target.hold.id, undefined, { idempotencyKey: key })
                : api.holds.release(target.hold.id, { idempotencyKey: key }),
            );
            if (res) {
              toast("success", target.kind === "capture" ? "Hold captured" : "Hold released");
              setTarget(null);
            }
          }}
        >
          <ActionResult status={act.status} message={act.message} success="Done." />
        </ConfirmDialog>
      )}
    </>
  );
}

function StatementPanel({ wallet }: { wallet: Wallet }) {
  const st = useQuery({ queryKey: ["statement", wallet.id], queryFn: () => api.wallets.statement(wallet.id) });
  const columns: Column<StatementLine>[] = [
    {
      key: "entry",
      header: "Entry",
      primary: true,
      cell: (l) => (
        <div>
          <Link
            to={`/ledger/entries/${l.entry_id}`}
            className="font-medium text-fg hover:text-primary"
            onClick={(e) => e.stopPropagation()}
          >
            #{l.entry_number} · {l.description}
          </Link>
          <div className="text-xs text-faint">{humanize(l.kind)}</div>
        </div>
      ),
    },
    {
      key: "when",
      header: "Date",
      cell: (l) => <span className="whitespace-nowrap text-[13px] text-muted">{dateTime(l.created_at)}</span>,
    },
    {
      key: "amount",
      header: "Amount",
      align: "right",
      cell: (l) => (
        <Money amount={l.amount} currency={wallet.currency} signed={l.direction === "credit" ? "in" : "out"} />
      ),
    },
    {
      key: "balance",
      header: "Balance",
      align: "right",
      cell: (l) => <Money amount={l.balance_after} currency={wallet.currency} className="text-fg" />,
    },
  ];
  if (st.error) return <ErrorState error={st.error} onRetry={() => void st.refetch()} />;
  return (
    <>
      {st.data && (
        <div className="grid grid-cols-2 gap-4 border-b border-border px-5 py-4 text-[13px] sm:grid-cols-4">
          <div>
            <div className="text-faint">Opening</div>
            <Money amount={st.data.opening_balance} currency={wallet.currency} />
          </div>
          <div>
            <div className="text-faint">Credits</div>
            <Money amount={st.data.total_credits} currency={wallet.currency} className="text-success" />
          </div>
          <div>
            <div className="text-faint">Debits</div>
            <Money amount={st.data.total_debits} currency={wallet.currency} />
          </div>
          <div>
            <div className="text-faint">Closing</div>
            <Money amount={st.data.closing_balance} currency={wallet.currency} className="text-fg" />
          </div>
        </div>
      )}
      <DataTable
        caption="Statement"
        columns={columns}
        rows={st.data ? [...st.data.lines].reverse() : undefined}
        rowKey={(l) => String(l.posting_id)}
        empty={<EmptyState icon={<WalletIcon />} title="No posted activity" />}
      />
    </>
  );
}

export function WalletDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { can } = useSession();
  const wallet = useQuery({ queryKey: ["wallets", id], queryFn: () => api.wallets.get(id) });
  const txs = useQuery({
    queryKey: ["transactions", { wallet: id }],
    queryFn: () => api.transactions.list({ wallet_id: id, limit: 25 }),
  });
  const [dialog, setDialog] = useState<"credit" | "debit" | "hold" | null>(null);
  const [statusAction, setStatusAction] = useState<"suspend" | "activate" | "close" | null>(null);
  const changeStatus = useMutation({
    mutationFn: (a: "suspend" | "activate" | "close") =>
      a === "suspend" ? api.wallets.suspend(id) : a === "activate" ? api.wallets.activate(id) : api.wallets.close(id),
    onSuccess: (w) => {
      void qc.invalidateQueries({ queryKey: ["wallets"] });
      toast("success", `Wallet ${w.status}`);
      setStatusAction(null);
    },
    onError: (err) => {
      toast("error", "Status change failed", humanError(err));
      setStatusAction(null);
    },
  });

  if (wallet.error)
    return (
      <Card>
        <ErrorState error={wallet.error} onRetry={() => void wallet.refetch()} />
      </Card>
    );
  const w = wallet.data;
  return (
    <>
      <PageHeader
        eyebrow={
          <Link to="/wallets" className="hover:text-fg">
            Wallets
          </Link>
        }
        title={
          w ? (
            <span className="flex items-center gap-3">
              {w.name} <StatusBadge status={w.status} />
            </span>
          ) : (
            <Skeleton className="h-7 w-48" />
          )
        }
        description={
          w && (
            <span className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs">{w.owner_reference}</span>
              <CopyId value={w.id} label="wallet id" />
              <span className="text-faint">·</span>
              <span className="text-xs">Created {dateTime(w.created_at)}</span>
            </span>
          )
        }
        actions={
          w &&
          w.status !== "closed" && (
            <>
              {can("money:move") && w.status === "active" && (
                <Button variant="primary" onClick={() => navigate(`/transfer?from=${w.id}`)}>
                  <Send /> Transfer
                </Button>
              )}
              {can("money:fund") && w.status === "active" && (
                <Button onClick={() => setDialog("credit")}>
                  <ArrowDownLeft /> Add funds
                </Button>
              )}
              {can("money:fund") && w.status === "active" && (
                <Button onClick={() => setDialog("debit")}>
                  <ArrowUpRight /> Withdraw
                </Button>
              )}
              {can("money:move") && w.status === "active" && (
                <Button onClick={() => setDialog("hold")}>
                  <Lock /> Hold
                </Button>
              )}
              {can("wallets:manage") &&
                (w.status === "active" ? (
                  <Button variant="ghost" onClick={() => setStatusAction("suspend")}>
                    <Pause /> Suspend
                  </Button>
                ) : (
                  <Button variant="ghost" onClick={() => setStatusAction("activate")}>
                    <Play /> Activate
                  </Button>
                ))}
              {can("wallets:manage") && (
                <Button variant="ghost" onClick={() => setStatusAction("close")}>
                  <Ban /> Close
                </Button>
              )}
            </>
          )
        }
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        {[
          ["Available", w?.balance.available, "Posted minus outgoing holds"],
          ["Posted balance", w?.balance.posted, "Sum of posted journal lines"],
          ["On hold", w?.balance.pending_outgoing, "Reserved by active holds"],
        ].map(([label, value, sub]) => (
          <Card key={label as string} className="p-5">
            <div className="text-[13px] font-medium text-muted">{label as string}</div>
            <div className="tabular mt-2 text-2xl font-semibold tracking-tight text-fg">
              {w ? formatMoney(value as number, w.currency) : <Skeleton className="h-8 w-32" />}
            </div>
            <div className="mt-1 text-xs text-faint">{sub as string}</div>
          </Card>
        ))}
      </div>
      {w && (
        <Card>
          <Tabs defaultValue="activity">
            <div className="px-5 pt-3">
              <TabsList
                items={[
                  { value: "activity", label: "Transactions" },
                  { value: "statement", label: "Statement" },
                  { value: "holds", label: "Holds" },
                ]}
              />
            </div>
            <TabsContent value="activity">
              {txs.error ? (
                <ErrorState error={txs.error} />
              ) : (
                <DataTable
                  caption="Wallet transactions"
                  columns={txColumns(w.id)}
                  rows={txs.data?.data}
                  rowKey={(t) => t.id}
                  onRowClick={(t) => navigate(`/transactions/${t.id}`)}
                  empty={<EmptyState icon={<WalletIcon />} title="No transactions yet" />}
                />
              )}
            </TabsContent>
            <TabsContent value="statement">
              <StatementPanel wallet={w} />
            </TabsContent>
            <TabsContent value="holds">
              <HoldsPanel wallet={w} />
            </TabsContent>
          </Tabs>
        </Card>
      )}
      {w && dialog && dialog !== "hold" && (
        <FundingDialog wallet={w} kind={dialog} open onOpenChange={(o) => !o && setDialog(null)} />
      )}
      {w && dialog === "hold" && <HoldDialog wallet={w} open onOpenChange={(o) => !o && setDialog(null)} />}
      {statusAction && (
        <ConfirmDialog
          open
          onOpenChange={(o) => !o && setStatusAction(null)}
          loading={changeStatus.isPending}
          danger={statusAction !== "activate"}
          title={`${humanize(statusAction)} wallet?`}
          description={
            statusAction === "suspend"
              ? "Suspended wallets cannot send, receive or reserve funds until reactivated. Existing history is unchanged."
              : statusAction === "close"
                ? "Closing is permanent and only allowed with a zero balance and no active holds."
                : "The wallet will be able to move money again."
          }
          confirmLabel={humanize(statusAction)}
          onConfirm={() => changeStatus.mutate(statusAction)}
        />
      )}
    </>
  );
}
