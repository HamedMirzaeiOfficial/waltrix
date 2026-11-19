import { AlertTriangle, ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import { Component, useState, type ErrorInfo, type ReactNode } from "react";

import { humanError } from "@/lib/errors";
import { formatMoney, humanize } from "@/lib/format";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";

import { Badge, Button, Skeleton } from "./primitives";

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  align?: "left" | "right";
  className?: string;
  /** Hide in the stacked mobile card. */
  hideOnMobile?: boolean;
  /** Use as the card title on mobile. */
  primary?: boolean;
}

/**
 * Accessible table on desktop; stacked cards below `md`. Rows can be activated by
 * click or Enter for keyboard users.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  loading,
  empty,
  caption,
}: {
  columns: Column<T>[];
  rows: T[] | undefined;
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  loading?: boolean;
  empty?: ReactNode;
  caption: string;
}) {
  if (loading || !rows) return <TableSkeleton columns={columns.length} />;
  if (rows.length === 0) return <>{empty}</>;
  const interactive = Boolean(onRowClick);
  const activate = (row: T) => (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onRowClick?.(row);
    }
  };
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className="border-b border-border">
              {columns.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  className={cn(
                    "whitespace-nowrap px-5 py-2.5 text-start text-xs font-medium uppercase tracking-wide text-faint",
                    c.align === "right" && "text-end",
                    c.className,
                  )}
                >
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={rowKey(row)}
                tabIndex={interactive ? 0 : undefined}
                onClick={interactive ? () => onRowClick?.(row) : undefined}
                onKeyDown={interactive ? activate(row) : undefined}
                className={cn(
                  "border-b border-border/70 last:border-0 transition-colors",
                  interactive && "cursor-pointer hover:bg-surface-hover focus-visible:bg-surface-hover",
                )}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={cn("px-5 py-3 align-middle", c.align === "right" && "text-end", c.className)}
                  >
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="divide-y divide-border md:hidden" aria-label={caption}>
        {rows.map((row) => {
          const primary = columns.find((c) => c.primary) ?? columns[0]!;
          return (
            <li
              key={rowKey(row)}
              tabIndex={interactive ? 0 : undefined}
              onClick={interactive ? () => onRowClick?.(row) : undefined}
              onKeyDown={interactive ? activate(row) : undefined}
              className={cn("space-y-2 px-4 py-3.5", interactive && "cursor-pointer active:bg-surface-hover")}
            >
              <div className="text-sm font-medium text-fg">{primary.cell(row)}</div>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[13px]">
                {columns
                  .filter((c) => c !== primary && !c.hideOnMobile)
                  .map((c) => (
                    <div key={c.key} className="min-w-0">
                      <dt className="text-[11px] uppercase tracking-wide text-faint">{c.header}</dt>
                      <dd className="truncate text-fg-2">{c.cell(row)}</dd>
                    </div>
                  ))}
              </dl>
            </li>
          );
        })}
      </ul>
    </>
  );
}

export function TableSkeleton({ columns = 5, rows = 6 }: { columns?: number; rows?: number }) {
  return (
    <div className="space-y-0 p-2" aria-busy="true" aria-label={t("Loading")}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex gap-4 px-3 py-3">
          {Array.from({ length: columns }, (_, j) => (
            <Skeleton key={j} className={cn("h-4", j === 0 ? "w-1/4" : "flex-1")} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Cursor pagination: keeps a stack of previous cursors so "Previous" works without offsets. */
export function useCursorPager() {
  const [stack, setStack] = useState<(string | undefined)[]>([undefined]);
  const cursor = stack[stack.length - 1];
  return {
    cursor,
    page: stack.length,
    next: (c: string | null) => c && setStack((s) => [...s, c]),
    prev: () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s)),
    reset: () => setStack([undefined]),
  };
}

export function Pager({
  page,
  hasMore,
  onPrev,
  onNext,
  busy,
}: {
  page: number;
  hasMore: boolean;
  onPrev: () => void;
  onNext: () => void;
  busy?: boolean;
}) {
  if (page === 1 && !hasMore) return null;
  return (
    <nav aria-label={t("Pagination")} className="flex items-center justify-between border-t border-border px-5 py-3">
      <span className="text-xs text-muted">{t("Page {page}", { page })}</span>
      <div className="flex gap-2">
        <Button size="sm" onClick={onPrev} disabled={page === 1 || busy} aria-label={t("Previous page")}>
          <ChevronLeft className="rtl:-scale-x-100" /> {t("Previous")}
        </Button>
        <Button size="sm" onClick={onNext} disabled={!hasMore || busy} aria-label={t("Next page")}>
          {t("Next")} <ChevronRight className="rtl:-scale-x-100" />
        </Button>
      </div>
    </nav>
  );
}

const STATUS_TONE: Record<string, "success" | "danger" | "warning" | "info" | "neutral" | "primary"> = {
  posted: "success",
  captured: "success",
  active: "success",
  passed: "success",
  failed: "danger",
  closed: "neutral",
  reversed: "neutral",
  released: "neutral",
  expired: "warning",
  pending: "warning",
  suspended: "warning",
  created: "info",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge tone={STATUS_TONE[status] ?? "neutral"} dot>
      {humanize(status)}
    </Badge>
  );
}

export function Money({
  amount,
  currency,
  signed,
  className,
}: {
  amount: number | null | undefined;
  currency: string;
  signed?: "debit" | "credit" | "in" | "out";
  className?: string;
}) {
  if (amount === null || amount === undefined) return <span className="text-faint">-</span>;
  const negative = signed === "out" || signed === "debit";
  return (
    <span
      dir="ltr"
      className={cn(
        "tabular whitespace-nowrap font-medium",
        signed === "in" && "text-success",
        negative && "text-fg-2",
        className,
      )}
    >
      {signed === "in" ? "+" : negative ? "−" : ""}
      {formatMoney(amount, currency)}
    </span>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center px-6 py-12 text-center">
      <div className="mb-3 grid size-10 place-items-center rounded-xl bg-danger-soft text-danger">
        <AlertTriangle className="size-5" />
      </div>
      <p className="text-sm font-medium text-fg">{t("Could not load this data")}</p>
      <p className="mt-1 max-w-sm text-[13px] text-muted">{humanError(error)}</p>
      {onRetry && (
        <Button size="sm" className="mt-4" onClick={onRetry}>
          <RefreshCw /> {t("Try again")}
        </Button>
      )}
    </div>
  );
}

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  override state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI error", error, info.componentStack);
  }

  override render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="card mx-auto mt-16 max-w-md p-8 text-center">
        <p className="text-base font-semibold text-fg">{t("This screen crashed")}</p>
        <p className="mt-2 text-sm text-muted">
          {t("No financial operation was affected by this display error. Reload to continue.")}
        </p>
        <Button className="mt-5" variant="primary" onClick={() => window.location.reload()}>
          {t("Reload")}
        </Button>
      </div>
    );
  }
}
