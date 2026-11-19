import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ApiKey, ApiKeyCreated, AuditEvent, Member, ReconciliationRun, Role } from "@waltrix/sdk";
import {
  AlertOctagon,
  CheckCircle2,
  KeyRound,
  ListChecks,
  Play,
  Plus,
  RotateCw,
  ScrollText,
  ShieldCheck,
  Trash2,
  TriangleAlert,
  Users,
} from "lucide-react";
import { useState } from "react";

import { DataTable, ErrorState, Pager, StatusBadge, useCursorPager, type Column } from "@/components/ui/data";
import { ConfirmDialog, Dialog, Select } from "@/components/ui/overlays";
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
import { toast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { humanError } from "@/lib/errors";
import { dateTime, formatMoney, humanize, relative } from "@/lib/format";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

// --- reconciliation ---------------------------------------------------------------------

const CHECK_LABELS: Record<string, string> = {
  unbalanced_entry: "Every entry balances per currency",
  short_entry: "Every entry has at least two postings",
  trial_balance: "Organization trial balance is zero",
  posted_balance_mismatch: "Posted balances match the journal",
  pending_balance_mismatch: "Pending balances match active holds",
  overdraft: "No protected account is overdrawn",
  posted_without_entry: "Posted transactions have journal entries",
  failed_with_postings: "Failed transactions moved no money",
  reversal_total_mismatch: "Reversal totals match their originals",
  hold_state_mismatch: "Hold and transaction states agree",
  overdue_hold: "No active hold is past its expiry",
  funding_vs_wallets: "Simulated funding equals wallet liabilities",
};

function RunReport({ run }: { run: ReconciliationRun }) {
  return (
    <div className="space-y-6">
      <div
        className={cn(
          "flex flex-wrap items-center gap-4 rounded-xl border p-5",
          run.status === "passed" ? "border-success/25 bg-success-soft" : "border-danger/30 bg-danger-soft",
        )}
      >
        {run.status === "passed" ? (
          <CheckCircle2 className="size-8 text-success" />
        ) : (
          <AlertOctagon className="size-8 text-danger" />
        )}
        <div className="min-w-0 flex-1">
          <div className="text-base font-semibold text-fg">
            {run.status === "passed" ? "Ledger reconciled" : "Reconciliation found problems"}
          </div>
          <div className="text-sm text-fg-2">
            {run.summary.errors} error(s), {run.summary.warnings} warning(s) · {dateTime(run.created_at)} ·{" "}
            {run.duration_ms} ms
          </div>
        </div>
        <CopyId value={run.id} label="run id" />
      </div>
      <div className="grid gap-6 2xl:grid-cols-2">
        <Card>
          <CardHeader title="Checks" description="Re-derived from the journal in one consistent snapshot" />
          <ul className="divide-y divide-border">
            {Object.keys(CHECK_LABELS)
              .filter((name) => name in run.summary.checks)
              .map((name) => [name, run.summary.checks[name] ?? 0] as const)
              .map(([name, count]) => {
                const warn = name === "overdue_hold";
                return (
                  <li key={name} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                    <span className="flex items-center gap-2.5 text-fg-2">
                      {count === 0 ? (
                        <CheckCircle2 className="size-4 text-success" />
                      ) : warn ? (
                        <TriangleAlert className="size-4 text-warning" />
                      ) : (
                        <AlertOctagon className="size-4 text-danger" />
                      )}
                      {CHECK_LABELS[name] ?? humanize(name)}
                    </span>
                    <span
                      className={cn("tabular text-xs", count ? (warn ? "text-warning" : "text-danger") : "text-faint")}
                    >
                      {count === 0 ? "OK" : `${count} found`}
                    </span>
                  </li>
                );
              })}
          </ul>
        </Card>
        <Card>
          <CardHeader title="Trial balance" description="Posted debits and credits per currency" />
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Trial balance</caption>
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-faint">
                  <th scope="col" className="px-5 py-2 font-medium">
                    Currency
                  </th>
                  <th scope="col" className="px-5 py-2 text-right font-medium">
                    Debits
                  </th>
                  <th scope="col" className="px-5 py-2 text-right font-medium">
                    Credits
                  </th>
                  <th scope="col" className="px-5 py-2 text-right font-medium">
                    Entries
                  </th>
                </tr>
              </thead>
              <tbody>
                {run.summary.trial_balance.map((r) => (
                  <tr key={r.currency} className="border-b border-border/60 last:border-0">
                    <td className="px-5 py-2.5 font-mono text-xs text-fg">{r.currency}</td>
                    <td className="tabular px-5 py-2.5 text-right text-fg-2">{formatMoney(r.debits, r.currency)}</td>
                    <td className="tabular px-5 py-2.5 text-right text-fg-2">{formatMoney(r.credits, r.currency)}</td>
                    <td className="tabular px-5 py-2.5 text-right text-muted">{r.entries}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {run.summary.trial_balance.length === 0 && (
              <p className="px-5 py-6 text-sm text-muted">No posted entries yet.</p>
            )}
          </div>
        </Card>
      </div>
      {run.findings.length > 0 && (
        <Card>
          <CardHeader title="Findings" description="Investigate each finding; corrections must be reversing entries." />
          <ul className="divide-y divide-border">
            {run.findings.map((f, i) => (
              <li key={i} className="px-5 py-3 text-sm">
                <div className="flex items-center gap-2">
                  <Badge tone={f.severity === "error" ? "danger" : "warning"}>{f.severity}</Badge>
                  <span className="font-medium text-fg">{CHECK_LABELS[f.check] ?? f.check}</span>
                </div>
                <pre className="mt-2 overflow-x-auto rounded-lg bg-bg/60 p-3 font-mono text-xs text-fg-2">
                  {JSON.stringify(f.details, null, 2)}
                </pre>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

export function ReconciliationPage() {
  const { can } = useSession();
  const qc = useQueryClient();
  const runs = useQuery({ queryKey: ["reconciliation"], queryFn: () => api.reconciliation.list({ limit: 20 }) });
  const [selected, setSelected] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: () => api.reconciliation.run(),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["reconciliation"] });
      void qc.invalidateQueries({ queryKey: ["overview"] });
      setSelected(r.id);
      toast(
        r.status === "passed" ? "success" : "warning",
        r.status === "passed" ? "All checks passed" : "Issues found",
        `${r.summary.errors} errors, ${r.summary.warnings} warnings`,
      );
    },
    onError: (err) => toast("error", "Reconciliation failed to run", humanError(err)),
  });
  const list = runs.data?.data ?? [];
  const current = list.find((r) => r.id === selected) ?? list[0];
  return (
    <>
      <PageHeader
        title="Reconciliation"
        description="Verifies cached balances, holds and transaction states against the immutable journal."
        actions={
          can("reconciliation:run") && (
            <Button variant="primary" loading={run.isPending} onClick={() => run.mutate()}>
              <Play /> Run now
            </Button>
          )
        }
      />
      {runs.error ? (
        <Card>
          <ErrorState error={runs.error} />
        </Card>
      ) : !runs.data ? (
        <Skeleton className="h-80 rounded-[14px]" />
      ) : !current ? (
        <Card>
          <EmptyState
            icon={<ListChecks />}
            title="No reconciliation runs yet"
            description="Run the first reconciliation to produce a report."
          />
        </Card>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_280px]">
          <RunReport run={current} />
          <Card className="h-fit">
            <CardHeader title="History" />
            <ul className="divide-y divide-border">
              {list.map((r) => (
                <li key={r.id}>
                  <button
                    onClick={() => setSelected(r.id)}
                    className={cn(
                      "flex w-full items-center justify-between px-5 py-3 text-left text-sm hover:bg-surface-hover",
                      r.id === current.id && "bg-primary-soft",
                    )}
                  >
                    <span className="text-fg-2">{relative(r.created_at)}</span>
                    <StatusBadge status={r.status} />
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      )}
    </>
  );
}

// --- audit ---------------------------------------------------------------------------------

export function AuditPage() {
  const pager = useCursorPager();
  const [action, setAction] = useState("");
  const q = useQuery({
    queryKey: ["audit", { action, cursor: pager.cursor }],
    queryFn: () => api.auditEvents.list({ limit: 50, cursor: pager.cursor, action: action || undefined }),
    placeholderData: keepPreviousData,
  });
  const columns: Column<AuditEvent>[] = [
    {
      key: "action",
      header: "Action",
      primary: true,
      cell: (e) => <span className="font-mono text-[13px] text-fg">{e.action}</span>,
    },
    {
      key: "actor",
      header: "Actor",
      cell: (e) => (
        <div className="min-w-0">
          <div className="truncate text-fg-2">{e.actor_label ?? "-"}</div>
          <div className="text-xs text-faint">{humanize(e.actor_type)}</div>
        </div>
      ),
    },
    {
      key: "target",
      header: "Target",
      cell: (e) =>
        e.target_id ? (
          <span className="text-[13px] text-muted">
            {e.target_type} <CopyId value={e.target_id} />
          </span>
        ) : (
          <span className="text-faint">-</span>
        ),
    },
    {
      key: "meta",
      header: "Details",
      hideOnMobile: true,
      cell: (e) => (
        <span className="block max-w-[260px] truncate font-mono text-xs text-faint" title={JSON.stringify(e.metadata)}>
          {Object.entries(e.metadata)
            .map(([k, v]) => `${k}=${String(v)}`)
            .join(" ") || "-"}
        </span>
      ),
    },
    {
      key: "cid",
      header: "Correlation",
      hideOnMobile: true,
      cell: (e) => (e.correlation_id ? <CopyId value={e.correlation_id} /> : <span className="text-faint">-</span>),
    },
    {
      key: "when",
      header: "Time",
      align: "right",
      cell: (e) => (
        <span className="whitespace-nowrap text-[13px] text-muted" title={dateTime(e.created_at)}>
          {relative(e.created_at)}
        </span>
      ),
    },
  ];
  return (
    <>
      <PageHeader
        title="Audit log"
        description="Who did what, when, and under which request. Append-only and separate from financial postings."
      />
      <Card>
        <div className="flex border-b border-border p-4">
          <Select
            aria-label="Action filter"
            className="sm:w-60"
            value={action || "all"}
            onValueChange={(v) => {
              setAction(v === "all" ? "" : v);
              pager.reset();
            }}
            options={[
              { value: "all", label: "All actions" },
              ...[
                "transfer",
                "deposit",
                "withdrawal",
                "hold",
                "transaction",
                "wallet",
                "api_key",
                "member",
                "reconciliation",
                "organization",
              ].map((a) => ({ value: a, label: `${a}.*` })),
            ]}
          />
        </div>
        {q.error ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : (
          <DataTable
            caption="Audit events"
            columns={columns}
            rows={q.data?.data}
            rowKey={(e) => e.id}
            empty={<EmptyState icon={<ScrollText />} title="No audit events" />}
          />
        )}
        <Pager
          page={pager.page}
          hasMore={q.data?.has_more ?? false}
          busy={q.isFetching}
          onPrev={pager.prev}
          onNext={() => pager.next(q.data?.next_cursor ?? null)}
        />
      </Card>
    </>
  );
}

// --- API keys --------------------------------------------------------------------------------

const KEY_ROLES = ["finance_operator", "auditor", "viewer"] as const;

function SecretReveal({ created, onClose }: { created: ApiKeyCreated; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Copy your API key now"
      description="This is the only time the secret is shown. Waltrix stores only a hash."
    >
      <div className="space-y-4">
        <div className="break-all rounded-lg border border-border bg-bg/70 p-3 font-mono text-[13px] text-fg">
          {created.secret}
        </div>
        <div className="flex items-start gap-2 rounded-lg bg-warning-soft p-3 text-[13px] text-fg-2">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" /> Store it in a secret manager. Never ship it
          to a browser or commit it to git.
        </div>
        <div className="flex justify-end gap-2">
          <Button onClick={() => void navigator.clipboard?.writeText(created.secret).then(() => setCopied(true))}>
            {copied ? "Copied" : "Copy"}
          </Button>
          <Button variant="primary" onClick={onClose}>
            I saved it
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

export function ApiKeysPage() {
  const qc = useQueryClient();
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: () => api.apiKeys.list() });
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [role, setRole] = useState<(typeof KEY_ROLES)[number]>("finance_operator");
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [confirm, setConfirm] = useState<{ key: ApiKey; kind: "revoke" | "rotate" } | null>(null);
  const done = (k: ApiKeyCreated) => {
    void qc.invalidateQueries({ queryKey: ["api-keys"] });
    setCreated(k);
  };
  const create = useMutation({
    mutationFn: () => api.apiKeys.create({ name, role }),
    onSuccess: (k) => {
      setCreating(false);
      setName("");
      done(k);
    },
  });
  const mutateKey = useMutation({
    mutationFn: (c: { key: ApiKey; kind: "revoke" | "rotate" }) =>
      c.kind === "revoke" ? api.apiKeys.revoke(c.key.id) : api.apiKeys.rotate(c.key.id, 0),
    onSuccess: (res, c) => {
      setConfirm(null);
      if (c.kind === "rotate") done(res as ApiKeyCreated);
      else {
        void qc.invalidateQueries({ queryKey: ["api-keys"] });
        toast("success", "Key revoked");
      }
    },
    onError: (err) => toast("error", "Action failed", humanError(err)),
  });
  const columns: Column<ApiKey>[] = [
    {
      key: "name",
      header: "Key",
      primary: true,
      cell: (k) => (
        <div>
          <div className="font-medium text-fg">{k.name}</div>
          <div className="font-mono text-xs text-faint">{k.prefix}_••••</div>
        </div>
      ),
    },
    { key: "role", header: "Role", cell: (k) => <Badge tone="primary">{humanize(k.role)}</Badge> },
    {
      key: "status",
      header: "Status",
      cell: (k) => (
        <StatusBadge
          status={k.revoked_at ? "revoked" : k.expires_at && new Date(k.expires_at) < new Date() ? "expired" : "active"}
        />
      ),
    },
    {
      key: "used",
      header: "Last used",
      cell: (k) => (
        <span className="text-[13px] text-muted">{k.last_used_at ? relative(k.last_used_at) : "Never"}</span>
      ),
    },
    {
      key: "created",
      header: "Created",
      hideOnMobile: true,
      cell: (k) => <span className="text-[13px] text-muted">{dateTime(k.created_at)}</span>,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (k) =>
        !k.revoked_at && (
          <div className="flex justify-end gap-1.5">
            <Button size="sm" onClick={() => setConfirm({ key: k, kind: "rotate" })}>
              <RotateCw /> Rotate
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Revoke ${k.name}`}
              onClick={() => setConfirm({ key: k, kind: "revoke" })}
            >
              <Trash2 />
            </Button>
          </div>
        ),
    },
  ];
  return (
    <>
      <PageHeader
        title="API keys"
        description="Server-to-server credentials scoped to this organization. Keys cannot manage members or other keys."
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus /> New key
          </Button>
        }
      />
      <Card>
        {keys.error ? (
          <ErrorState error={keys.error} />
        ) : (
          <DataTable
            caption="API keys"
            columns={columns}
            rows={keys.data}
            rowKey={(k) => k.id}
            empty={
              <EmptyState
                icon={<KeyRound />}
                title="No API keys"
                description="Create a key to integrate your backend with the Waltrix API or SDKs."
              />
            }
          />
        )}
      </Card>
      <Card className="mt-6 p-5 text-[13px] text-muted">
        <div className="mb-2 flex items-center gap-2 font-medium text-fg">
          <ShieldCheck className="size-4 text-primary" /> Rotation guidance
        </div>
        Rotate keys regularly and immediately when someone with access leaves. Rotation issues a new secret and revokes
        the old one; deploy the new secret first if you need zero downtime (the API also supports a grace period).
      </Card>
      <Dialog open={creating} onOpenChange={setCreating} title="Create API key">
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) create.mutate();
          }}
        >
          <Field label="Name" htmlFor="key-name" hint="Where it will be used, e.g. checkout-service (prod).">
            <Input id="key-name" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Role" htmlFor="key-role">
            <Select
              id="key-role"
              value={role}
              onValueChange={(v) => setRole(v as typeof role)}
              options={KEY_ROLES.map((r) => ({ value: r, label: humanize(r) }))}
            />
          </Field>
          {create.error && (
            <p role="alert" className="text-sm text-danger">
              {humanError(create.error)}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" onClick={() => setCreating(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={create.isPending} disabled={!name.trim()}>
              Create key
            </Button>
          </div>
        </form>
      </Dialog>
      {created && <SecretReveal created={created} onClose={() => setCreated(null)} />}
      {confirm && (
        <ConfirmDialog
          open
          onOpenChange={(o) => !o && setConfirm(null)}
          danger
          loading={mutateKey.isPending}
          title={confirm.kind === "revoke" ? `Revoke "${confirm.key.name}"?` : `Rotate "${confirm.key.name}"?`}
          description={
            confirm.kind === "revoke"
              ? "Requests using this key will fail immediately. This cannot be undone."
              : "A new secret is issued and the current one stops working immediately."
          }
          confirmLabel={confirm.kind === "revoke" ? "Revoke" : "Rotate"}
          onConfirm={() => mutateKey.mutate(confirm)}
        />
      )}
    </>
  );
}

// --- organization & members -------------------------------------------------------------

const ROLES: Role[] = ["owner", "admin", "finance_operator", "auditor", "viewer"];
const ROLE_HELP: Record<Role, string> = {
  owner: "Everything, including organization settings.",
  admin: "Everything except organization settings.",
  finance_operator: "Wallets, transfers, holds, funding, reversals.",
  auditor: "Read-only plus audit log and reconciliation runs.",
  viewer: "Read-only wallets, transactions and ledger.",
};

export function OrganizationSettingsPage() {
  const { membership, can, refresh } = useSession();
  const [name, setName] = useState(membership?.organization.name ?? "");
  const save = useMutation({
    mutationFn: () => api.organizations.update({ name }),
    onSuccess: async () => {
      await refresh();
      toast("success", "Organization updated");
    },
    onError: (e) => toast("error", "Update failed", humanError(e)),
  });
  return (
    <>
      <PageHeader
        title="Organization"
        description="Tenant settings. All data in Waltrix is isolated per organization."
      />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-6">
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <Field
              label="Organization name"
              htmlFor="org-name"
              hint={can("org:manage") ? undefined : "Only owners can rename the organization."}
            >
              <Input
                id="org-name"
                value={name}
                disabled={!can("org:manage")}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            {can("org:manage") && (
              <Button
                type="submit"
                variant="primary"
                loading={save.isPending}
                disabled={!name.trim() || name === membership?.organization.name}
              >
                Save
              </Button>
            )}
          </form>
        </Card>
        <Card className="p-6 text-sm">
          <dl className="space-y-3">
            <div className="flex justify-between">
              <dt className="text-muted">Organization id</dt>
              <dd>
                <CopyId value={membership?.organization.id ?? ""} size={36} />
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">Slug</dt>
              <dd className="font-mono text-xs text-fg-2">{membership?.organization.slug}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">Your role</dt>
              <dd>
                <Badge tone="primary">{humanize(membership?.role)}</Badge>
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">Created</dt>
              <dd className="text-fg-2">{dateTime(membership?.organization.created_at)}</dd>
            </div>
          </dl>
          <div className="mt-5 border-t border-border pt-4">
            <div className="mb-2 text-xs font-medium uppercase tracking-wider text-faint">Your permissions</div>
            <div className="flex flex-wrap gap-1.5">
              {membership?.permissions.map((p) => (
                <Badge key={p}>{p}</Badge>
              ))}
            </div>
          </div>
        </Card>
      </div>
    </>
  );
}

export function MembersPage() {
  const { can, me } = useSession();
  const qc = useQueryClient();
  const members = useQuery({ queryKey: ["members"], queryFn: () => api.members.list() });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [removing, setRemoving] = useState<Member | null>(null);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["members"] });
  const add = useMutation({
    mutationFn: () => api.members.add({ email, role }),
    onSuccess: () => {
      setEmail("");
      refresh();
      toast("success", "Member added");
    },
    onError: (e) => toast("error", "Could not add member", humanError(e)),
  });
  const update = useMutation({
    mutationFn: (v: { id: string; role: Role }) => api.members.updateRole(v.id, v.role),
    onSuccess: () => {
      refresh();
      toast("success", "Role updated");
    },
    onError: (e) => toast("error", "Role change failed", humanError(e)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.members.remove(id),
    onSuccess: () => {
      setRemoving(null);
      refresh();
      toast("success", "Member removed");
    },
    onError: (e) => {
      setRemoving(null);
      toast("error", "Could not remove member", humanError(e));
    },
  });
  const manage = can("members:manage");
  const columns: Column<Member>[] = [
    {
      key: "user",
      header: "Member",
      primary: true,
      cell: (m) => (
        <div className="flex items-center gap-3">
          <span className="grid size-8 place-items-center rounded-full bg-surface-2 text-xs font-semibold">
            {m.user.display_name.charAt(0).toUpperCase()}
          </span>
          <div>
            <div className="font-medium text-fg">
              {m.user.display_name}
              {m.user.id === me?.user.id && <span className="ml-2 text-xs text-muted">(you)</span>}
            </div>
            <div className="text-xs text-muted">{m.user.email}</div>
          </div>
        </div>
      ),
    },
    {
      key: "role",
      header: "Role",
      cell: (m) =>
        manage && m.user.id !== me?.user.id ? (
          <Select
            aria-label={`Role for ${m.user.email}`}
            className="h-8 w-44"
            value={m.role}
            onValueChange={(r) => update.mutate({ id: m.id, role: r as Role })}
            options={ROLES.map((r) => ({ value: r, label: humanize(r) }))}
          />
        ) : (
          <Badge tone="primary">{humanize(m.role)}</Badge>
        ),
    },
    {
      key: "since",
      header: "Joined",
      cell: (m) => <span className="text-[13px] text-muted">{dateTime(m.created_at)}</span>,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (m) =>
        manage &&
        m.user.id !== me?.user.id && (
          <Button size="sm" variant="ghost" aria-label={`Remove ${m.user.email}`} onClick={() => setRemoving(m)}>
            <Trash2 />
          </Button>
        ),
    },
  ];
  return (
    <>
      <PageHeader
        title="Members & permissions"
        description="Roles are enforced by the API on every request; the UI only mirrors them."
      />
      {manage && (
        <Card className="mb-6 p-5">
          <form
            className="flex flex-col gap-3 sm:flex-row sm:items-end"
            onSubmit={(e) => {
              e.preventDefault();
              if (email.trim()) add.mutate();
            }}
          >
            <Field label="Add existing user by email" htmlFor="m-email" className="flex-1">
              <Input
                id="m-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="teammate@company.com"
              />
            </Field>
            <Field label="Role" htmlFor="m-role" className="sm:w-52">
              <Select
                id="m-role"
                value={role}
                onValueChange={(v) => setRole(v as Role)}
                options={ROLES.map((r) => ({ value: r, label: humanize(r) }))}
              />
            </Field>
            <Button type="submit" variant="primary" loading={add.isPending} disabled={!email.trim()}>
              <Plus /> Add
            </Button>
          </form>
        </Card>
      )}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          {members.error ? (
            <ErrorState error={members.error} />
          ) : (
            <DataTable
              caption="Members"
              columns={columns}
              rows={members.data}
              rowKey={(m) => m.id}
              empty={<EmptyState icon={<Users />} title="No members" />}
            />
          )}
        </Card>
        <Card className="h-fit">
          <CardHeader title="Roles" />
          <ul className="divide-y divide-border">
            {ROLES.map((r) => (
              <li key={r} className="px-5 py-3">
                <div className="text-sm font-medium text-fg">{humanize(r)}</div>
                <div className="text-[13px] text-muted">{ROLE_HELP[r]}</div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      {removing && (
        <ConfirmDialog
          open
          onOpenChange={(o) => !o && setRemoving(null)}
          danger
          loading={remove.isPending}
          title={`Remove ${removing.user.email}?`}
          description="They lose access to this organization immediately. Their past actions stay in the audit log."
          confirmLabel="Remove"
          onConfirm={() => remove.mutate(removing.id)}
        />
      )}
    </>
  );
}
