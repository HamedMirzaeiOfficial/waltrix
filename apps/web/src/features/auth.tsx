import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Building2, Plus, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useNavigate } from "react-router-dom";
import { z } from "zod";

import { LanguageButton, Logo } from "@/components/layout/AppShell";
import { Badge, Button, Card, Field, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { humanError } from "@/lib/errors";
import { humanize } from "@/lib/format";
import { msg, t, tMaybe } from "@/lib/i18n";
import { useSession } from "@/lib/session";

const loginSchema = z.object({
  email: z.string().trim().email(msg("Enter a valid email")),
  password: z.string().min(1, msg("Password is required")),
  display_name: z.string().max(120).optional(),
});
type LoginForm = z.infer<typeof loginSchema>;

function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative grid min-h-dvh place-items-center overflow-hidden bg-bg px-4 py-10">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-[480px] w-[880px] -translate-x-1/2 rounded-full opacity-60 blur-3xl"
        style={{ background: "radial-gradient(closest-side, var(--primary-soft), transparent)" }}
      />
      <LanguageButton className="absolute end-4 top-4" />
      <div className="relative w-full max-w-[400px]">
        <Logo className="mb-8 justify-center" />
        {children}
        <p className="mt-6 text-center text-xs text-faint">
          {t("Financial infrastructure, built for correctness. Demo data is synthetic; no real bank is connected.")}
        </p>
      </div>
    </div>
  );
}

export function LoginPage() {
  const { me, refresh } = useSession();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const form = useForm<LoginForm>({ resolver: zodResolver(loginSchema) });

  if (me) return <Navigate to="/" replace />;

  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      if (mode === "register") {
        if (values.password.length < 10) {
          form.setError("password", { message: msg("Use at least 10 characters") });
          return;
        }
        await api.auth.register({ email: values.email, password: values.password, display_name: values.display_name });
      }
      await api.auth.login({ email: values.email, password: values.password });
      await refresh();
      navigate("/organizations");
    } catch (err) {
      setError(humanError(err));
    }
  });

  return (
    <AuthLayout>
      <Card className="p-7">
        <h1 className="text-lg font-semibold text-fg">{mode === "login" ? t("Sign in") : t("Create your account")}</h1>
        <p className="mt-1 text-sm text-muted">
          {mode === "login"
            ? t("Welcome back to your financial operations.")
            : t("Start with your own sandbox organization.")}
        </p>
        <form className="mt-6 space-y-4" onSubmit={onSubmit} noValidate>
          {mode === "register" && (
            <Field label={t("Name")} htmlFor="display_name">
              <Input id="display_name" autoComplete="name" {...form.register("display_name")} />
            </Field>
          )}
          <Field label={t("Email")} htmlFor="email" error={tMaybe(form.formState.errors.email?.message)}>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              aria-invalid={Boolean(form.formState.errors.email) || undefined}
              {...form.register("email")}
            />
          </Field>
          <Field
            label={t("Password")}
            htmlFor="password"
            error={tMaybe(form.formState.errors.password?.message)}
            hint={mode === "register" ? t("At least 10 characters.") : undefined}
          >
            <Input
              id="password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              aria-invalid={Boolean(form.formState.errors.password) || undefined}
              {...form.register("password")}
            />
          </Field>
          {error && (
            <p
              role="alert"
              className="rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[13px] text-danger"
            >
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" size="lg" className="w-full" loading={form.formState.isSubmitting}>
            {mode === "login" ? t("Sign in") : t("Create account")} <ArrowRight className="rtl:-scale-x-100" />
          </Button>
        </form>
        <div className="mt-5 text-center text-[13px] text-muted">
          {mode === "login" ? t("New to Waltrix?") : t("Already have an account?")}{" "}
          <button
            type="button"
            className="font-medium text-primary hover:underline"
            onClick={() => {
              setError(null);
              setMode(mode === "login" ? "register" : "login");
            }}
          >
            {mode === "login" ? t("Create an account") : t("Sign in")}
          </button>
        </div>
      </Card>
    </AuthLayout>
  );
}

export function OrganizationsPage() {
  const { me, membership, selectOrganization } = useSession();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: (n: string) => api.organizations.create({ name: n }),
    onSuccess: async (org) => {
      await qc.invalidateQueries({ queryKey: ["me"] });
      selectOrganization(org.id);
      navigate("/");
    },
  });
  if (!me) return <Navigate to="/login" replace />;
  return (
    <AuthLayout>
      <Card className="p-7">
        <h1 className="text-lg font-semibold text-fg">{t("Choose an organization")}</h1>
        <p className="mt-1 text-sm text-muted">
          {t("Data is isolated per organization. Your role is set by each organization.")}
        </p>
        <ul className="mt-5 space-y-2">
          {me.memberships.map((m) => (
            <li key={m.organization.id}>
              <button
                className="flex w-full items-center gap-3 rounded-xl border border-border px-4 py-3 text-start transition-colors hover:border-primary/50 hover:bg-surface-hover"
                onClick={() => {
                  selectOrganization(m.organization.id);
                  navigate("/");
                }}
              >
                <span className="grid size-9 place-items-center rounded-lg bg-primary-soft text-primary">
                  <Building2 className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-fg">{m.organization.name}</span>
                  <span className="text-xs text-muted">{humanize(m.role)}</span>
                </span>
                {membership?.organization.id === m.organization.id && <Badge tone="primary">{t("Current")}</Badge>}
              </button>
            </li>
          ))}
          {me.memberships.length === 0 && (
            <li className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-sm text-muted">
              <ShieldCheck className="mx-auto mb-2 size-5" />
              {t("You are not a member of any organization yet. Create one below.")}
            </li>
          )}
        </ul>
        <form
          className="mt-6 flex gap-2 border-t border-border pt-5"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) create.mutate(name.trim());
          }}
        >
          <Input
            aria-label={t("New organization name")}
            placeholder={t("New organization name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Button type="submit" variant="primary" loading={create.isPending} disabled={!name.trim()}>
            <Plus /> {t("Create")}
          </Button>
        </form>
        {create.error && <p className="mt-2 text-xs text-danger">{humanError(create.error)}</p>}
      </Card>
    </AuthLayout>
  );
}
