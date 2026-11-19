import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as SelectPrimitive from "@radix-ui/react-select";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { Check, ChevronDown, X } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { Button } from "./primitives";

const overlay = "fixed inset-0 z-40 bg-black/55 backdrop-blur-[2px] data-[state=open]:animate-fade-up";
const panel =
  "fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-2xl " +
  "border border-border bg-surface shadow-pop focus:outline-none data-[state=open]:animate-fade-up";

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  trigger,
  wide,
}: {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  trigger?: ReactNode;
  wide?: boolean;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      {trigger && <DialogPrimitive.Trigger asChild>{trigger}</DialogPrimitive.Trigger>}
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={overlay} />
        <DialogPrimitive.Content className={cn(panel, wide && "max-w-2xl")}>
          <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-4">
            <div>
              <DialogPrimitive.Title className="text-base font-semibold text-fg">{title}</DialogPrimitive.Title>
              {description ? (
                <DialogPrimitive.Description className="mt-1 text-[13px] text-muted">
                  {description}
                </DialogPrimitive.Description>
              ) : (
                <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
              )}
            </div>
            <DialogPrimitive.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Close" className="-mr-2 -mt-1 size-8">
                <X />
              </Button>
            </DialogPrimitive.Close>
          </div>
          <div className="max-h-[75dvh] overflow-y-auto px-6 py-5">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/** Confirmation for consequential actions. The confirm button shows progress and cannot be double-clicked. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  loading,
  danger,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  loading?: boolean;
  danger?: boolean;
  children?: ReactNode;
}) {
  return (
    <AlertDialogPrimitive.Root open={open} onOpenChange={(o) => !loading && onOpenChange(o)}>
      <AlertDialogPrimitive.Portal>
        <AlertDialogPrimitive.Overlay className={overlay} />
        <AlertDialogPrimitive.Content className={cn(panel, "max-w-md p-6")}>
          <AlertDialogPrimitive.Title className="text-base font-semibold text-fg">{title}</AlertDialogPrimitive.Title>
          <AlertDialogPrimitive.Description className="mt-2 text-sm text-muted">
            {description}
          </AlertDialogPrimitive.Description>
          {children && <div className="mt-4">{children}</div>}
          <div className="mt-6 flex justify-end gap-2">
            <AlertDialogPrimitive.Cancel asChild>
              <Button disabled={loading}>Cancel</Button>
            </AlertDialogPrimitive.Cancel>
            <Button variant={danger ? "danger" : "primary"} loading={loading} onClick={onConfirm}>
              {confirmLabel}
            </Button>
          </div>
        </AlertDialogPrimitive.Content>
      </AlertDialogPrimitive.Portal>
    </AlertDialogPrimitive.Root>
  );
}

export function Select({
  value,
  onValueChange,
  options,
  placeholder,
  id,
  className,
  "aria-label": ariaLabel,
  invalid,
}: {
  value: string | undefined;
  onValueChange: (value: string) => void;
  options: { value: string; label: ReactNode; hint?: ReactNode; disabled?: boolean }[];
  placeholder?: string;
  id?: string;
  className?: string;
  "aria-label"?: string;
  invalid?: boolean;
}) {
  return (
    <SelectPrimitive.Root value={value} onValueChange={onValueChange}>
      <SelectPrimitive.Trigger
        id={id}
        aria-label={ariaLabel}
        aria-invalid={invalid || undefined}
        className={cn(
          "flex h-10 w-full items-center justify-between gap-2 rounded-lg border border-border bg-bg/60 px-3 text-left",
          "text-sm text-fg hover:border-border-strong focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40",
          "data-[placeholder]:text-faint aria-invalid:border-danger",
          className,
        )}
      >
        <span className="min-w-0 truncate">
          <SelectPrimitive.Value placeholder={placeholder} />
        </span>
        <SelectPrimitive.Icon>
          <ChevronDown className="size-4 text-muted" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={6}
          className="z-50 max-h-80 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-xl border border-border bg-surface p-1 shadow-pop"
        >
          <SelectPrimitive.Viewport>
            {options.map((o) => (
              <SelectPrimitive.Item
                key={o.value}
                value={o.value}
                disabled={o.disabled}
                className="relative flex cursor-default select-none items-center justify-between gap-6 rounded-lg py-2 pl-3 pr-8 text-sm text-fg outline-none data-[disabled]:opacity-40 data-[highlighted]:bg-surface-hover"
              >
                <SelectPrimitive.ItemText>{o.label}</SelectPrimitive.ItemText>
                {o.hint && <span className="tabular text-xs text-muted">{o.hint}</span>}
                <SelectPrimitive.ItemIndicator className="absolute right-2.5">
                  <Check className="size-4 text-primary" />
                </SelectPrimitive.ItemIndicator>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}

export const Tabs = TabsPrimitive.Root;
export const TabsContent = TabsPrimitive.Content;

export function TabsList({ items }: { items: { value: string; label: ReactNode }[] }) {
  return (
    <TabsPrimitive.List className="mb-5 flex gap-1 border-b border-border">
      {items.map((i) => (
        <TabsPrimitive.Trigger
          key={i.value}
          value={i.value}
          className="relative -mb-px border-b-2 border-transparent px-3 pb-2.5 pt-1 text-sm font-medium text-muted transition-colors hover:text-fg data-[state=active]:border-primary data-[state=active]:text-fg"
        >
          {i.label}
        </TabsPrimitive.Trigger>
      ))}
    </TabsPrimitive.List>
  );
}

export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <TooltipPrimitive.Root delayDuration={250}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          sideOffset={6}
          className="z-50 max-w-xs rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-xs text-fg shadow-pop"
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export const TooltipProvider = TooltipPrimitive.Provider;
