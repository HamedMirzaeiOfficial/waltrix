"""``waltrix`` command-line tool.

waltrix migrate              apply database migrations
waltrix serve                run the API with uvicorn
waltrix seed-demo            create a SYNTHETIC demo organization
waltrix expire-holds         release overdue holds (run from cron / a scheduler)
waltrix reconcile            run reconciliation for every organization
waltrix purge-idempotency    delete expired idempotency records
"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from uuid import UUID

from sqlalchemy import select

from waltrix_core.db import make_engine, make_session_factory
from waltrix_core.db.models import Organization, User
from waltrix_core.enums import ActorType, Role
from waltrix_core.migrate import upgrade
from waltrix_core.services import idempotency, identity, operations, reconciliation, wallets
from waltrix_core.services.context import Actor
from waltrix_core.services.runner import OperationResult

from .settings import get_settings

DEMO_EMAIL = "demo@waltrix.dev"
DEMO_PASSWORD = "waltrix-demo-password"  # noqa: S105 - synthetic local-only credential, printed on purpose
DEMO_ORG = "Northwind Demo (synthetic data)"


def _sessions():  # type: ignore[no-untyped-def]
    return make_session_factory(make_engine(get_settings().database_url))


def _rid(result: OperationResult) -> UUID:
    if result.resource_id is None:
        raise RuntimeError(f"{result.operation} failed: {result.error_code}")
    return result.resource_id


def cmd_migrate(_: argparse.Namespace) -> int:
    upgrade(get_settings().database_url)
    print("migrations applied")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("waltrix_api.asgi:app", host=args.host, port=args.port, reload=args.reload, access_log=False)
    return 0


def cmd_seed_demo(args: argparse.Namespace) -> int:
    """Create a demo org with clearly synthetic customers and history.

    Every amount below is generated here; none of it is real financial data.
    """
    factory = _sessions()
    db = factory()
    rng = random.Random(args.seed)  # noqa: S311 - deterministic synthetic data, not security
    existing = db.execute(select(User).where(User.email == DEMO_EMAIL)).scalar_one_or_none()
    db.commit()
    if existing:
        print(f"demo user already exists: {DEMO_EMAIL}")
        return 0
    user = identity.register_user(db, email=DEMO_EMAIL, password=DEMO_PASSWORD, display_name="Demo Operator")
    org = identity.create_organization(db, user, name=DEMO_ORG)
    actor = Actor(org.id, ActorType.USER, str(user.id), user.email, Role.OWNER, "seed-demo")

    people = [
        "Ada Synthetic",
        "Linus Example",
        "Grace Sample",
        "Alan Placeholder",
        "Marie Fictional",
        "Edsger Testcase",
        "Barbara Mock",
        "Ken Dummy",
    ]
    usd = []
    for i, name in enumerate(people):
        r = wallets.create_wallet(
            db,
            actor,
            name=name,
            owner_reference=f"demo_cust_{i + 1:03d}",
            currency="USD",
            metadata={"synthetic": True},
        )
        usd.append(_rid(r))
        operations.deposit(
            db,
            actor,
            wallet_id=_rid(r),
            amount=rng.randint(50, 900) * 100,
            currency="USD",
            description="Demo funding (simulated)",
            idempotency_key=f"seed-fund-{i}",
        )
    merchant = _rid(
        wallets.create_wallet(
            db,
            actor,
            name="Demo Coffee Merchant",
            owner_reference="demo_merchant_001",
            currency="USD",
            metadata={"synthetic": True},
        )
    )
    eur = []
    for i, name in enumerate(["Euro Synthetic GmbH", "Example SARL"]):
        r = wallets.create_wallet(
            db,
            actor,
            name=name,
            owner_reference=f"demo_eu_{i + 1:03d}",
            currency="EUR",
            metadata={"synthetic": True},
        )
        eur.append(_rid(r))
        operations.deposit(
            db,
            actor,
            wallet_id=_rid(r),
            amount=rng.randint(100, 2000) * 100,
            currency="EUR",
            description="Demo funding (simulated)",
            idempotency_key=f"seed-eur-{i}",
        )
    operations.transfer(
        db,
        actor,
        source_wallet_id=eur[0],
        destination_wallet_id=eur[1],
        amount=12_500,
        currency="EUR",
        description="Invoice INV-DEMO-1",
        idempotency_key="seed-eur-t",
    )

    posted = []
    for n in range(40):
        a, b = rng.sample(usd, 2)
        r = operations.transfer(
            db,
            actor,
            source_wallet_id=a,
            destination_wallet_id=b,
            amount=rng.randint(5, 250) * 100,
            currency="USD",
            description=rng.choice(
                ["Rent split", "Dinner", "Concert tickets", "Loan repayment", "Gift", "Shared groceries"]
            ),
            idempotency_key=f"seed-t-{n}",
        )
        if r.succeeded:
            posted.append(_rid(r))
    for n in range(6):
        h = operations.create_hold(
            db,
            actor,
            wallet_id=rng.choice(usd),
            destination_wallet_id=merchant,
            amount=rng.randint(3, 12) * 100,
            currency="USD",
            description="Card authorization",
            idempotency_key=f"seed-h-{n}",
        )
        if h.succeeded and n % 3 == 0:
            operations.capture_hold(db, actor, hold_id=_rid(h), idempotency_key=f"seed-c-{n}")
        elif h.succeeded and n % 3 == 1:
            operations.release_hold(db, actor, hold_id=_rid(h), idempotency_key=f"seed-r-{n}")
    # A deliberate failure (overspend) and a refund so the dashboard shows real examples of both.
    operations.transfer(
        db,
        actor,
        source_wallet_id=usd[0],
        destination_wallet_id=usd[1],
        amount=10_000_000,
        currency="USD",
        description="Too large (demo failure)",
        idempotency_key="seed-fail",
    )
    if posted:
        operations.reverse_transaction(
            db, actor, transaction_id=posted[0], reason="Demo refund", idempotency_key="seed-rev"
        )
    reconciliation.run_reconciliation(db, actor)
    _, secret = identity.create_api_key(db, actor, name="Demo integration key", role=Role.FINANCE_OPERATOR)
    print("Synthetic demo data created.")
    print(f"  login:    {DEMO_EMAIL} / {DEMO_PASSWORD}")
    print(f"  org id:   {org.id}")
    print(f"  API key:  {secret}  (finance_operator, shown once)")
    db.close()
    return 0


def cmd_expire_holds(args: argparse.Namespace) -> int:
    db = _sessions()()
    n = operations.expire_holds(db, limit=args.limit)
    print(f"expired {n} hold(s)")
    return 0


def cmd_reconcile(_: argparse.Namespace) -> int:
    db = _sessions()()
    org_ids = list(db.execute(select(Organization.id)).scalars())
    db.commit()
    failed = 0
    for org_id in org_ids:
        run = reconciliation.run_reconciliation(db, Actor.system(org_id, "reconcile-cli", uuid.uuid4().hex))
        print(f"{org_id}: {run.status} errors={run.summary['errors']} warnings={run.summary['warnings']}")
        failed += run.status != "passed"
    return 1 if failed else 0


def cmd_purge(_: argparse.Namespace) -> int:
    db = _sessions()()
    with db.begin():
        n = idempotency.purge_expired(db)
    print(f"purged {n} expired idempotency record(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="waltrix")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=4820)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(fn=cmd_serve)
    seed = sub.add_parser("seed-demo")
    seed.add_argument("--seed", type=int, default=7)
    seed.set_defaults(fn=cmd_seed_demo)
    exp = sub.add_parser("expire-holds")
    exp.add_argument("--limit", type=int, default=500)
    exp.set_defaults(fn=cmd_expire_holds)
    sub.add_parser("reconcile").set_defaults(fn=cmd_reconcile)
    sub.add_parser("purge-idempotency").set_defaults(fn=cmd_purge)
    args = parser.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
