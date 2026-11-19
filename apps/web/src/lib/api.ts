import { Waltrix } from "@waltrix/sdk";

/**
 * The dashboard uses the same public SDK and REST API as external integrations.
 * Session mode: httpOnly cookie + CSRF header; the organization header is
 * re-verified by the server against the user's membership on every request.
 */
const ORG_KEY = "waltrix-org";

function readOrg(): string | null {
  try {
    return localStorage.getItem(ORG_KEY);
  } catch {
    return null;
  }
}

let organizationId: string | null = readOrg();

export function getOrganizationId(): string | null {
  return organizationId;
}

export function setOrganizationId(id: string | null): void {
  organizationId = id;
  try {
    if (id) localStorage.setItem(ORG_KEY, id);
    else localStorage.removeItem(ORG_KEY);
  } catch {
    /* storage unavailable: keep in memory */
  }
}

export const api = new Waltrix({
  baseUrl: import.meta.env.BASE_URL.replace(/\/$/, ""),
  session: { organizationId: () => organizationId },
  timeoutMs: 15_000,
  maxRetries: 2,
});
