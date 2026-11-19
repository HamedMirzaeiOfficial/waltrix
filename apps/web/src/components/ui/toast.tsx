import * as ToastPrimitive from "@radix-ui/react-toast";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { useSyncExternalStore, type ReactNode } from "react";

import { cn } from "@/lib/utils";

type Tone = "success" | "error" | "info" | "warning";
interface ToastItem {
  id: number;
  tone: Tone;
  title: string;
  description?: ReactNode;
}

let items: ToastItem[] = [];
let nextId = 1;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function toast(tone: Tone, title: string, description?: ReactNode): void {
  items = [...items.slice(-3), { id: nextId++, tone, title, description }];
  emit();
}

function dismiss(id: number) {
  items = items.filter((t) => t.id !== id);
  emit();
}

const ICONS = { success: CheckCircle2, error: XCircle, info: Info, warning: AlertTriangle };
const TONES = { success: "text-success", error: "text-danger", info: "text-info", warning: "text-warning" };

export function Toaster() {
  const list = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => items,
  );
  return (
    <ToastPrimitive.Provider swipeDirection="right" duration={5000}>
      {list.map((t) => {
        const Icon = ICONS[t.tone];
        return (
          <ToastPrimitive.Root
            key={t.id}
            onOpenChange={(open) => !open && dismiss(t.id)}
            className="card flex items-start gap-3 p-4 shadow-pop data-[state=open]:animate-fade-up"
          >
            <Icon className={cn("mt-0.5 size-5 shrink-0", TONES[t.tone])} aria-hidden />
            <div className="min-w-0 flex-1">
              <ToastPrimitive.Title className="text-sm font-medium text-fg">{t.title}</ToastPrimitive.Title>
              {t.description && (
                <ToastPrimitive.Description className="mt-0.5 text-[13px] text-muted">
                  {t.description}
                </ToastPrimitive.Description>
              )}
            </div>
            <ToastPrimitive.Close aria-label="Dismiss" className="text-muted hover:text-fg">
              <X className="size-4" />
            </ToastPrimitive.Close>
          </ToastPrimitive.Root>
        );
      })}
      <ToastPrimitive.Viewport className="fixed bottom-4 right-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2 outline-none" />
    </ToastPrimitive.Provider>
  );
}
