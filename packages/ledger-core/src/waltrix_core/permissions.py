"""Role-based permissions.

Roles are coarse bundles of fine-grained permissions. Authorization checks in
the engine and API always ask for a *permission*, never compare role names, so
roles can be re-shaped without touching call sites.
"""

from __future__ import annotations

from enum import StrEnum

from .enums import Role


class Permission(StrEnum):
    LEDGER_READ = "ledger:read"
    WALLETS_READ = "wallets:read"
    WALLETS_MANAGE = "wallets:manage"
    MONEY_MOVE = "money:move"  # transfers, holds, captures, releases
    MONEY_FUND = "money:fund"  # simulated deposits and withdrawals
    MONEY_REVERSE = "money:reverse"
    LEDGER_MANUAL_ENTRY = "ledger:manual_entry"
    ACCOUNTS_MANAGE = "accounts:manage"
    RECONCILIATION_READ = "reconciliation:read"
    RECONCILIATION_RUN = "reconciliation:run"
    AUDIT_READ = "audit:read"
    API_KEYS_MANAGE = "api_keys:manage"
    MEMBERS_READ = "members:read"
    MEMBERS_MANAGE = "members:manage"
    ORG_MANAGE = "org:manage"


P = Permission
_READ = {P.LEDGER_READ, P.WALLETS_READ}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(Permission),
    Role.ADMIN: frozenset(set(Permission) - {P.ORG_MANAGE}),
    Role.FINANCE_OPERATOR: frozenset(
        _READ
        | {
            P.WALLETS_MANAGE,
            P.MONEY_MOVE,
            P.MONEY_FUND,
            P.MONEY_REVERSE,
            P.RECONCILIATION_READ,
            P.MEMBERS_READ,
        }
    ),
    Role.AUDITOR: frozenset(
        _READ | {P.RECONCILIATION_READ, P.RECONCILIATION_RUN, P.AUDIT_READ, P.MEMBERS_READ}
    ),
    Role.VIEWER: frozenset(_READ),
}

# Roles an API key may carry. Keys are for servers; they never manage people or keys.
API_KEY_ROLES = frozenset({Role.FINANCE_OPERATOR, Role.AUDITOR, Role.VIEWER})

# Ordering used to stop privilege escalation: an actor can grant at most their own rank.
ROLE_RANK: dict[Role, int] = {
    Role.VIEWER: 1,
    Role.AUDITOR: 2,
    Role.FINANCE_OPERATOR: 3,
    Role.ADMIN: 4,
    Role.OWNER: 5,
}


def permissions_for(role: Role | str) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[Role(role)]


def has_permission(role: Role | str, permission: Permission) -> bool:
    return permission in permissions_for(role)
