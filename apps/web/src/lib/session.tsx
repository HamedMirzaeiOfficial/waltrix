import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Me, Membership } from "@waltrix/sdk";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { api, getOrganizationId, setOrganizationId } from "./api";
import { isAuthError } from "./errors";

interface SessionValue {
  me: Me | null;
  loading: boolean;
  membership: Membership | null;
  can: (permission: string) => boolean;
  selectOrganization: (id: string) => void;
  signOut: () => Promise<void>;
  refresh: () => Promise<unknown>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api.auth.me();
      } catch (err) {
        if (isAuthError(err)) return null;
        throw err;
      }
    },
    staleTime: 60_000,
  });
  const me = meQuery.data ?? null;
  // The id lives in api.ts (the SDK reads it on every request) *and* in state here. Reading only the
  // module variable during render was a bug: choosing an organization changed it without re-rendering
  // this provider, so RequireOrg saw the old (null) membership and bounced back to /organizations.
  const [orgId, setOrgId] = useState(getOrganizationId);
  const membership = me?.memberships.find((m) => m.organization.id === orgId) ?? null;

  const selectOrganization = useCallback(
    (id: string) => {
      setOrganizationId(id);
      setOrgId(id);
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      void qc.invalidateQueries({ queryKey: ["me"] });
    },
    [qc],
  );

  const signOut = useCallback(async () => {
    await api.auth.logout().catch(() => undefined);
    setOrganizationId(null);
    setOrgId(null);
    qc.clear();
    await qc.invalidateQueries({ queryKey: ["me"] });
  }, [qc]);

  const value = useMemo<SessionValue>(
    () => ({
      me,
      loading: meQuery.isPending,
      membership,
      can: (p) => membership?.permissions.includes(p) ?? false,
      selectOrganization,
      signOut,
      refresh: () => meQuery.refetch(),
    }),
    [me, meQuery, membership, selectOrganization, signOut],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession outside SessionProvider");
  return ctx;
}
