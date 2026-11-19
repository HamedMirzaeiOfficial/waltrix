import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Check, Copy, Loader2 } from "lucide-react";
import { forwardRef, useState, type HTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-all " +
    "duration-150 select-none disabled:pointer-events-none disabled:opacity-50 active:translate-y-px " +
    "focus-visible:outline-2 focus-visible:outline-offset-2 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-primary text-on-primary shadow-[0_1px_0_rgb(255_255_255/0.18)_inset,0_1px_2px_rgb(0_0_0/0.3)] " +
          "hover:brightness-110",
        secondary: "bg-surface-2 text-fg border border-border hover:bg-surface-hover hover:border-border-strong",
        ghost: "text-fg-2 hover:bg-surface-hover hover:text-fg",
        outline: "border border-border text-fg hover:bg-surface-hover",
        danger: "bg-danger text-white hover:brightness-110",
        "danger-soft": "bg-danger-soft text-danger hover:brightness-125",
      },
      size: {
        sm: "h-8 px-3 text-[13px]",
        md: "h-9 px-3.5",
        lg: "h-11 px-5 text-[15px]",
        icon: "size-9",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, loading, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {asChild ? (
          children
        ) : (
          <>
            {loading && <Loader2 className="animate-spin" aria-hidden />}
            {children}
          </>
        )}
      </Comp>
    );
  },
);
Button.displayName = "Button";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-10 w-full rounded-lg border border-border bg-bg/60 px-3 text-sm text-fg placeholder:text-faint",
        "transition-colors hover:border-border-strong focus:border-primary focus:outline-none focus:ring-2 " +
          "focus:ring-ring/40 disabled:opacity-60 aria-invalid:border-danger aria-invalid:ring-danger/20",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export function Field({
  label,
  htmlFor,
  error,
  hint,
  children,
  className,
}: {
  label: string;
  htmlFor: string;
  error?: string | undefined;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={htmlFor} className="block text-[13px] font-medium text-fg-2">
        {label}
      </label>
      {children}
      {error ? (
        <p role="alert" id={`${htmlFor}-error`} className="text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-muted">{hint}</p>
      ) : null}
    </div>
  );
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("card", className)} {...props} />;
}

export function CardHeader({
  title,
  description,
  action,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4 border-b border-border px-5 py-4", className)}>
      <div className="min-w-0">
        <h2 className="text-sm font-semibold text-fg">{title}</h2>
        {description && <p className="mt-0.5 text-[13px] text-muted">{description}</p>}
      </div>
      {action}
    </div>
  );
}

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "bg-surface-2 text-fg-2 ring-border",
        primary: "bg-primary-soft text-primary ring-primary/25",
        success: "bg-success-soft text-success ring-success/25",
        danger: "bg-danger-soft text-danger ring-danger/25",
        warning: "bg-warning-soft text-warning ring-warning/25",
        info: "bg-info-soft text-info ring-info/25",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({
  tone,
  className,
  dot,
  children,
}: VariantProps<typeof badgeVariants> & { className?: string; dot?: boolean; children: ReactNode }) {
  return (
    <span className={cn(badgeVariants({ tone }), className)}>
      {dot && <span className="size-1.5 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn(
        "relative overflow-hidden rounded-md bg-surface-2 before:absolute before:inset-0 before:-translate-x-full",
        "before:bg-gradient-to-r before:from-transparent before:via-white/5 before:to-transparent",
        "before:animate-[shimmer_1.4s_infinite]",
        className,
      )}
    />
  );
}

export function CopyId({ value, label, size = 8 }: { value: string; label?: string; size?: number }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        void navigator.clipboard?.writeText(value).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        });
      }}
      title={value}
      aria-label={`Copy ${label ?? "id"} ${value}`}
      className="group inline-flex items-center gap-1 rounded-md px-1 font-mono text-xs text-muted hover:bg-surface-hover hover:text-fg"
    >
      {value.slice(0, size)}
      {copied ? (
        <Check className="size-3 text-success" />
      ) : (
        <Copy className="size-3 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
      )}
    </button>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted">
      {children}
    </kbd>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1.5 text-xs font-medium text-muted">{eyebrow}</div>}
        <h1 className="text-[22px] font-semibold tracking-tight text-fg">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-4 grid size-11 place-items-center rounded-xl border border-border bg-surface-2 text-muted [&_svg]:size-5">
        {icon}
      </div>
      <p className="text-sm font-medium text-fg">{title}</p>
      {description && <p className="mt-1 max-w-sm text-[13px] text-muted">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
  icon,
  tone,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon?: ReactNode;
  tone?: "danger" | "success" | "warning";
}) {
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-medium text-muted">{label}</span>
        {icon && (
          <span
            className={cn(
              "grid size-8 place-items-center rounded-lg bg-surface-2 text-muted [&_svg]:size-4",
              tone === "danger" && "bg-danger-soft text-danger",
              tone === "success" && "bg-success-soft text-success",
              tone === "warning" && "bg-warning-soft text-warning",
            )}
          >
            {icon}
          </span>
        )}
      </div>
      <div className="tabular mt-3 text-2xl font-semibold tracking-tight text-fg">{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </Card>
  );
}
