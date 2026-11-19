import { AlertTriangle, CheckCircle2, HelpCircle, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import type { ActionStatus } from "@/lib/useIdempotentAction";
import { cn } from "@/lib/utils";

/** Inline outcome banner for money-moving dialogs. Never shows success before the server confirms. */
export function ActionResult({
  status,
  message,
  success,
  failedTransactionId,
}: {
  status: ActionStatus;
  message: string | null;
  success: ReactNode;
  failedTransactionId?: string | null;
}) {
  if (status === "idle" || status === "pending") return null;
  const map = {
    success: {
      icon: CheckCircle2,
      tone: "border-success/25 bg-success-soft text-success",
      title: "Confirmed",
      body: success,
    },
    failed: {
      icon: XCircle,
      tone: "border-danger/30 bg-danger-soft text-danger",
      title: "Failed - no money moved",
      body: message,
    },
    rejected: {
      icon: AlertTriangle,
      tone: "border-warning/30 bg-warning-soft text-warning",
      title: "Not accepted",
      body: message,
    },
    unknown: {
      icon: HelpCircle,
      tone: "border-warning/30 bg-warning-soft text-warning",
      title: "Result unknown",
      body: `${message ?? ""} Retrying reuses the same idempotency key, so it cannot apply twice.`,
    },
  }[status];
  const Icon = map.icon;
  return (
    <div role="status" aria-live="polite" className={cn("flex gap-3 rounded-xl border p-3.5 text-sm", map.tone)}>
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 text-fg-2">
        <div className="font-medium text-fg">{map.title}</div>
        <div className="mt-0.5">{map.body}</div>
        {status === "failed" && failedTransactionId && (
          <Link
            to={`/transactions/${failedTransactionId}`}
            className="mt-1 inline-block font-mono text-xs text-primary hover:underline"
          >
            View failed transaction
          </Link>
        )}
      </div>
    </div>
  );
}
