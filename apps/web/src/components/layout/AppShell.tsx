import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  ArrowLeftRight,
  BookOpen,
  Building2,
  Check,
  ChevronsUpDown,
  KeyRound,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  Moon,
  ScrollText,
  Send,
  Sun,
  Users,
  Wallet,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/primitives";
import { humanize } from "@/lib/format";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
        <rect width="32" height="32" rx="8" className="fill-surface-2" />
        <path
          d="M7 9l4 14 5-10 5 10 4-14"
          fill="none"
          className="stroke-primary"
          strokeWidth="2.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className="text-[15px] font-semibold tracking-tight text-fg">Waltrix</span>
    </span>
  );
}

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  permission?: string;
}

const MAIN: NavItem[] = [
  { to: "/", label: "Overview", icon: <LayoutDashboard /> },
  { to: "/wallets", label: "Wallets", icon: <Wallet /> },
  { to: "/transfer", label: "Transfer", icon: <Send />, permission: "money:move" },
  { to: "/transactions", label: "Transactions", icon: <ArrowLeftRight /> },
  { to: "/ledger", label: "Ledger", icon: <BookOpen /> },
  { to: "/reconciliation", label: "Reconciliation", icon: <ListChecks />, permission: "reconciliation:read" },
  { to: "/audit", label: "Audit log", icon: <ScrollText />, permission: "audit:read" },
];

const SETTINGS: NavItem[] = [
  { to: "/settings/api-keys", label: "API keys", icon: <KeyRound />, permission: "api_keys:manage" },
  { to: "/settings/members", label: "Members", icon: <Users />, permission: "members:read" },
  { to: "/settings/organization", label: "Organization", icon: <Building2 /> },
];

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme ?? "dark");
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("waltrix-theme", next);
    } catch {
      /* ignore */
    }
    setTheme(next);
  };
  return [theme, toggle];
}

function NavSection({ items, label }: { items: NavItem[]; label?: string }) {
  const { can } = useSession();
  const visible = items.filter((i) => !i.permission || can(i.permission));
  if (!visible.length) return null;
  return (
    <div>
      {label && <div className="mb-1.5 px-3 text-[11px] font-medium uppercase tracking-wider text-faint">{label}</div>}
      <ul className="space-y-0.5">
        {visible.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                cn(
                  "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors [&_svg]:size-4",
                  isActive
                    ? "bg-primary-soft text-fg [&_svg]:text-primary"
                    : "text-muted hover:bg-surface-hover hover:text-fg",
                )
              }
            >
              {item.icon}
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </div>
  );
}

function OrgSwitcher() {
  const { me, membership, selectOrganization } = useSession();
  const navigate = useNavigate();
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          className="flex w-full items-center gap-3 rounded-xl border border-border bg-surface/60 px-3 py-2.5 text-left transition-colors hover:border-border-strong"
          aria-label="Switch organization"
        >
          <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary-soft text-[13px] font-semibold text-primary">
            {membership?.organization.name.charAt(0) ?? "?"}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium text-fg">{membership?.organization.name}</span>
            <span className="block text-xs text-muted">{humanize(membership?.role)}</span>
          </span>
          <ChevronsUpDown className="size-4 text-faint" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="start"
          sideOffset={6}
          className="z-50 w-64 rounded-xl border border-border bg-surface p-1 shadow-pop"
        >
          <DropdownMenu.Label className="px-2.5 py-1.5 text-[11px] uppercase tracking-wider text-faint">
            Organizations
          </DropdownMenu.Label>
          {me?.memberships.map((m) => (
            <DropdownMenu.Item
              key={m.organization.id}
              onSelect={() => {
                selectOrganization(m.organization.id);
                navigate("/");
              }}
              className="flex cursor-default items-center justify-between rounded-lg px-2.5 py-2 text-sm text-fg outline-none data-[highlighted]:bg-surface-hover"
            >
              <span className="truncate">{m.organization.name}</span>
              {m.organization.id === membership?.organization.id && <Check className="size-4 text-primary" />}
            </DropdownMenu.Item>
          ))}
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item
            onSelect={() => navigate("/organizations")}
            className="cursor-default rounded-lg px-2.5 py-2 text-sm text-muted outline-none data-[highlighted]:bg-surface-hover data-[highlighted]:text-fg"
          >
            Manage organizations
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  const { me, signOut } = useSession();
  const [theme, toggleTheme] = useTheme();
  const navigate = useNavigate();
  return (
    <div
      className="flex h-full flex-col gap-6 p-4"
      onClick={(e) => (e.target as HTMLElement).closest("a") && onNavigate?.()}
    >
      <Logo className="px-2 pt-1" />
      <OrgSwitcher />
      <nav aria-label="Main" className="flex-1 space-y-6 overflow-y-auto">
        <NavSection items={MAIN} />
        <NavSection items={SETTINGS} label="Settings" />
      </nav>
      <div className="flex items-center gap-2 border-t border-border pt-4">
        <div className="grid size-8 place-items-center rounded-full bg-surface-2 text-xs font-semibold text-fg-2">
          {me?.user.display_name.charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium text-fg">{me?.user.display_name}</div>
          <div className="truncate text-xs text-muted">{me?.user.email}</div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleTheme}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
        >
          {theme === "dark" ? <Sun /> : <Moon />}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Sign out"
          onClick={async () => {
            await signOut();
            navigate("/login");
          }}
        >
          <LogOut />
        </Button>
      </div>
    </div>
  );
}

export function AppShell() {
  const [drawer, setDrawer] = useState(false);
  const location = useLocation();
  useEffect(() => setDrawer(false), [location.pathname]);
  return (
    <div className="min-h-dvh bg-bg">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-surface focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-border bg-sidebar lg:block">
        <SidebarBody />
      </aside>
      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-sidebar/90 px-4 backdrop-blur lg:hidden">
        <Logo />
        <Button variant="ghost" size="icon" aria-label="Open menu" onClick={() => setDrawer(true)}>
          <Menu />
        </Button>
      </header>
      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="absolute inset-0 bg-black/60" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 left-0 w-72 max-w-[85vw] border-r border-border bg-sidebar animate-fade-up">
            <Button
              variant="ghost"
              size="icon"
              className="absolute right-3 top-3"
              aria-label="Close menu"
              onClick={() => setDrawer(false)}
            >
              <X />
            </Button>
            <SidebarBody onNavigate={() => setDrawer(false)} />
          </div>
        </div>
      )}
      <main id="main" className="lg:pl-64">
        <div className="mx-auto max-w-[1240px] px-4 py-6 sm:px-6 lg:px-10 lg:py-9">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
