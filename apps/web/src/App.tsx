import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WaltrixApiError } from "@waltrix/sdk";
import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/ui/data";
import { TooltipProvider } from "@/components/ui/overlays";
import { Skeleton } from "@/components/ui/primitives";
import { Toaster } from "@/components/ui/toast";
import { LoginPage, OrganizationsPage } from "@/features/auth";
import { OverviewPage } from "@/features/overview";
import { SessionProvider, useSession } from "@/lib/session";

const WalletsPage = lazy(() => import("@/features/wallets").then((m) => ({ default: m.WalletsPage })));
const WalletDetailPage = lazy(() => import("@/features/wallets").then((m) => ({ default: m.WalletDetailPage })));
const TransferPage = lazy(() => import("@/features/transfer/TransferPage").then((m) => ({ default: m.TransferPage })));
const TransactionsPage = lazy(() => import("@/features/transactions").then((m) => ({ default: m.TransactionsPage })));
const TransactionDetailPage = lazy(() =>
  import("@/features/transactions").then((m) => ({ default: m.TransactionDetailPage })),
);
const LedgerPage = lazy(() => import("@/features/ledger").then((m) => ({ default: m.LedgerPage })));
const JournalEntryPage = lazy(() => import("@/features/ledger").then((m) => ({ default: m.JournalEntryPage })));
const ReconciliationPage = lazy(() => import("@/features/admin").then((m) => ({ default: m.ReconciliationPage })));
const AuditPage = lazy(() => import("@/features/admin").then((m) => ({ default: m.AuditPage })));
const ApiKeysPage = lazy(() => import("@/features/admin").then((m) => ({ default: m.ApiKeysPage })));
const MembersPage = lazy(() => import("@/features/admin").then((m) => ({ default: m.MembersPage })));
const OrganizationSettingsPage = lazy(() =>
  import("@/features/admin").then((m) => ({ default: m.OrganizationSettingsPage })),
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: true,
      // The SDK already retries transient errors; never retry 4xx here.
      retry: (count, err) => !(err instanceof WaltrixApiError && err.status < 500) && count < 1,
    },
    // Mutations move money: they are never retried automatically by React Query.
    mutations: { retry: false },
  },
  queryCache: new QueryCache({
    onError: (err) => {
      if (err instanceof WaltrixApiError && err.status === 401)
        void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  }),
});

function FullPageLoader() {
  return (
    <div className="grid min-h-dvh place-items-center bg-bg" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-10 w-40" />
    </div>
  );
}

function RequireOrg() {
  const { me, loading, membership } = useSession();
  if (loading) return <FullPageLoader />;
  if (!me) return <Navigate to="/login" replace />;
  if (!membership) return <Navigate to="/organizations" replace />;
  return <Outlet />;
}

function RequirePermission({ permission }: { permission: string }) {
  const { can } = useSession();
  return can(permission) ? <Outlet /> : <Navigate to="/" replace />;
}

const PageFallback = () => <Skeleton className="h-96 rounded-[14px]" />;

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <ErrorBoundary>
          <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, "")}>
            <SessionProvider>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route path="/organizations" element={<OrganizationsPage />} />
                <Route element={<RequireOrg />}>
                  <Route element={<AppShell />}>
                    <Route
                      element={
                        <ErrorBoundary>
                          <Suspense fallback={<PageFallback />}>
                            <Outlet />
                          </Suspense>
                        </ErrorBoundary>
                      }
                    >
                      <Route index element={<OverviewPage />} />
                      <Route path="wallets" element={<WalletsPage />} />
                      <Route path="wallets/:id" element={<WalletDetailPage />} />
                      <Route element={<RequirePermission permission="money:move" />}>
                        <Route path="transfer" element={<TransferPage />} />
                      </Route>
                      <Route path="transactions" element={<TransactionsPage />} />
                      <Route path="transactions/:id" element={<TransactionDetailPage />} />
                      <Route path="ledger" element={<LedgerPage />} />
                      <Route path="ledger/entries/:id" element={<JournalEntryPage />} />
                      <Route element={<RequirePermission permission="reconciliation:read" />}>
                        <Route path="reconciliation" element={<ReconciliationPage />} />
                      </Route>
                      <Route element={<RequirePermission permission="audit:read" />}>
                        <Route path="audit" element={<AuditPage />} />
                      </Route>
                      <Route element={<RequirePermission permission="api_keys:manage" />}>
                        <Route path="settings/api-keys" element={<ApiKeysPage />} />
                      </Route>
                      <Route path="settings/members" element={<MembersPage />} />
                      <Route path="settings/organization" element={<OrganizationSettingsPage />} />
                      <Route path="*" element={<Navigate to="/" replace />} />
                    </Route>
                  </Route>
                </Route>
              </Routes>
            </SessionProvider>
          </BrowserRouter>
          <Toaster />
        </ErrorBoundary>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
