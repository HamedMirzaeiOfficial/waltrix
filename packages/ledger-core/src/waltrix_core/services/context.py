"""Who is acting, on behalf of which tenant.

An ``Actor`` is built by the transport layer *after* authentication from
server-side data (session -> membership, or API key row). It is never built
from tenant/role information supplied by a client.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ..enums import ActorType, Role
from ..errors import PermissionDenied
from ..permissions import Permission, has_permission


@dataclass(frozen=True, slots=True)
class Actor:
    org_id: UUID
    actor_type: ActorType
    actor_id: str | None
    label: str | None
    role: Role
    correlation_id: str | None = None

    def can(self, permission: Permission) -> bool:
        return has_permission(self.role, permission)

    def require(self, permission: Permission) -> None:
        if not self.can(permission):
            raise PermissionDenied(
                f"this action requires the '{permission}' permission",
                permission=str(permission),
            )

    @classmethod
    def system(cls, org_id: UUID, label: str = "system", correlation_id: str | None = None) -> Actor:
        return cls(org_id, ActorType.SYSTEM, None, label, Role.OWNER, correlation_id)
