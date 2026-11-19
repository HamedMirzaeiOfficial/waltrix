"""Reconciliation: re-derive everything from the journal and compare.

Checks (severity ``error`` fails the run, ``warning`` does not):

1. ``unbalanced_entry``          entry whose debits != credits in some currency   (error)
2. ``short_entry``               entry with fewer than two postings               (error)
3. ``trial_balance``             org-wide posted debits != credits per currency  (error)
4. ``posted_balance_mismatch``   account posted_* columns != sum of POSTED postings (error)
5. ``pending_balance_mismatch``  account pending_* != PENDING entries of ACTIVE holds (error)
6. ``overdraft``                 non-negative account with negative available     (error)
7. ``posted_without_entry``      POSTED/REVERSED transaction lacking a posted entry (error)
8. ``failed_with_postings``      FAILED non-hold transaction that has entries      (error)
9. ``reversal_total_mismatch``   reversed_amount != sum of posted reversals        (error)
10. ``hold_state_mismatch``      hold/transaction status disagree                  (error)
11. ``overdue_hold``             ACTIVE hold past its expiry (worker lagging)      (warning)
12. ``funding_vs_wallets``       simulated funding asset != wallet liabilities     (error)

(1) and (2) "should" be impossible thanks to the deferred trigger; checking
them anyway is the point of reconciliation: trust, but verify.

Everything runs in one REPEATABLE READ, READ ONLY transaction, so all checks
see the same snapshot even while money keeps moving.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db.models import ReconciliationRun
from ..enums import ReconciliationStatus
from ..permissions import Permission
from . import audit
from .context import Actor

CHECKS: list[tuple[str, str, str]] = [
    (
        "unbalanced_entry",
        "error",
        """
        SELECT p.entry_id::text AS id, p.currency,
               sum(CASE WHEN p.direction='debit' THEN p.amount ELSE 0 END) AS debits,
               sum(CASE WHEN p.direction='credit' THEN p.amount ELSE 0 END) AS credits
          FROM postings p WHERE p.org_id = :org
         GROUP BY p.entry_id, p.currency
        HAVING sum(CASE WHEN p.direction='debit' THEN p.amount ELSE -p.amount END) <> 0
        """,
    ),
    (
        "short_entry",
        "error",
        """
        SELECT e.id::text AS id, count(p.id) AS postings
          FROM journal_entries e LEFT JOIN postings p ON p.entry_id = e.id
         WHERE e.org_id = :org GROUP BY e.id HAVING count(p.id) < 2
        """,
    ),
    (
        "trial_balance",
        "error",
        """
        SELECT p.currency AS id,
               sum(CASE WHEN p.direction='debit' THEN p.amount ELSE 0 END) AS debits,
               sum(CASE WHEN p.direction='credit' THEN p.amount ELSE 0 END) AS credits
          FROM postings p JOIN journal_entries e ON e.id = p.entry_id
         WHERE p.org_id = :org AND e.phase = 'posted'
         GROUP BY p.currency
        HAVING sum(CASE WHEN p.direction='debit' THEN p.amount ELSE -p.amount END) <> 0
        """,
    ),
    (
        "posted_balance_mismatch",
        "error",
        """
        WITH derived AS (
          SELECT p.account_id,
                 sum(CASE WHEN p.direction='debit' THEN p.amount ELSE 0 END) AS debits,
                 sum(CASE WHEN p.direction='credit' THEN p.amount ELSE 0 END) AS credits
            FROM postings p JOIN journal_entries e ON e.id = p.entry_id
           WHERE p.org_id = :org AND e.phase = 'posted'
           GROUP BY p.account_id)
        SELECT a.id::text AS id, a.code,
               a.posted_debits AS cached_debits, coalesce(d.debits, 0) AS journal_debits,
               a.posted_credits AS cached_credits, coalesce(d.credits, 0) AS journal_credits
          FROM accounts a LEFT JOIN derived d ON d.account_id = a.id
         WHERE a.org_id = :org
           AND (a.posted_debits <> coalesce(d.debits, 0) OR a.posted_credits <> coalesce(d.credits, 0))
        """,
    ),
    (
        "pending_balance_mismatch",
        "error",
        """
        WITH derived AS (
          SELECT p.account_id,
                 sum(CASE WHEN p.direction='debit' THEN p.amount ELSE 0 END) AS debits,
                 sum(CASE WHEN p.direction='credit' THEN p.amount ELSE 0 END) AS credits
            FROM postings p
            JOIN journal_entries e ON e.id = p.entry_id
            JOIN holds h ON h.pending_entry_id = e.id
           WHERE p.org_id = :org AND e.phase = 'pending' AND h.status = 'active'
           GROUP BY p.account_id)
        SELECT a.id::text AS id, a.code,
               a.pending_debits AS cached_debits, coalesce(d.debits, 0) AS journal_debits,
               a.pending_credits AS cached_credits, coalesce(d.credits, 0) AS journal_credits
          FROM accounts a LEFT JOIN derived d ON d.account_id = a.id
         WHERE a.org_id = :org
           AND (a.pending_debits <> coalesce(d.debits, 0) OR a.pending_credits <> coalesce(d.credits, 0))
        """,
    ),
    (
        "overdraft",
        "error",
        """
        SELECT id::text AS id, code FROM accounts
         WHERE org_id = :org AND NOT allow_negative AND (
               (normal_balance = 'credit' AND posted_credits - posted_debits - pending_debits < 0)
            OR (normal_balance = 'debit' AND posted_debits - posted_credits - pending_credits < 0))
        """,
    ),
    (
        "posted_without_entry",
        "error",
        """
        SELECT t.id::text AS id, t.type, t.status FROM transactions t
         WHERE t.org_id = :org AND t.status IN ('posted', 'reversed')
           AND NOT EXISTS (SELECT 1 FROM journal_entries e
                            WHERE e.transaction_id = t.id AND e.phase = 'posted')
        """,
    ),
    (
        "failed_with_postings",
        "error",
        """
        SELECT t.id::text AS id, t.type FROM transactions t
         WHERE t.org_id = :org AND t.status = 'failed' AND t.type <> 'hold'
           AND EXISTS (SELECT 1 FROM journal_entries e WHERE e.transaction_id = t.id)
        """,
    ),
    (
        "reversal_total_mismatch",
        "error",
        """
        SELECT o.id::text AS id, o.reversed_amount AS recorded, coalesce(sum(r.posted_amount), 0) AS journal
          FROM transactions o
          LEFT JOIN transactions r ON r.original_transaction_id = o.id AND r.status = 'posted'
         WHERE o.org_id = :org AND o.type <> 'reversal'
         GROUP BY o.id, o.reversed_amount
        HAVING o.reversed_amount <> coalesce(sum(r.posted_amount), 0)
        """,
    ),
    (
        "hold_state_mismatch",
        "error",
        """
        SELECT h.id::text AS id, h.status AS hold_status, t.status AS transaction_status
          FROM holds h JOIN transactions t ON t.id = h.transaction_id
         WHERE h.org_id = :org AND NOT (
               (h.status = 'active' AND t.status = 'pending')
            OR (h.status = 'captured' AND t.status IN ('posted', 'reversed'))
            OR (h.status IN ('released', 'expired') AND t.status = 'failed'))
        """,
    ),
    (
        "overdue_hold",
        "warning",
        """
        SELECT id::text AS id, expires_at::text AS expires_at FROM holds
         WHERE org_id = :org AND status = 'active' AND expires_at < now()
        """,
    ),
    (
        "funding_vs_wallets",
        "error",
        """
        WITH f AS (
          SELECT currency, sum(posted_debits - posted_credits) AS funded
            FROM accounts WHERE org_id = :org AND code = 'system:simulated_funding' GROUP BY currency),
        w AS (
          SELECT a.currency, sum(a.posted_credits - a.posted_debits) AS owed
            FROM wallets wl JOIN accounts a ON a.id = wl.account_id
           WHERE wl.org_id = :org GROUP BY a.currency)
        SELECT coalesce(f.currency, w.currency) AS id,
               coalesce(f.funded, 0) AS funded, coalesce(w.owed, 0) AS owed_to_wallets
          FROM f FULL JOIN w ON f.currency = w.currency
         WHERE coalesce(f.funded, 0) <> coalesce(w.owed, 0)
        """,
    ),
]

MAX_FINDINGS_PER_CHECK = 50


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    return {
        k: (int(v) if isinstance(v, int) else (str(v) if v is not None else None)) for k, v in row.items()
    }


def run_checks(session: Session, org_id: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    per_check: dict[str, int] = {}
    for name, severity, sql in CHECKS:
        rows = session.execute(text(sql), {"org": org_id}).mappings().all()
        per_check[name] = len(rows)
        for row in rows[:MAX_FINDINGS_PER_CHECK]:
            findings.append({"check": name, "severity": severity, "details": _jsonable(dict(row))})
    totals = (
        session.execute(
            text(
                """
            SELECT p.currency,
                   sum(CASE WHEN p.direction='debit' THEN p.amount ELSE 0 END) AS debits,
                   sum(CASE WHEN p.direction='credit' THEN p.amount ELSE 0 END) AS credits,
                   count(DISTINCT p.entry_id) AS entries
              FROM postings p JOIN journal_entries e ON e.id = p.entry_id
             WHERE p.org_id = :org AND e.phase = 'posted' GROUP BY p.currency ORDER BY p.currency
            """
            ),
            {"org": org_id},
        )
        .mappings()
        .all()
    )
    counts = (
        session.execute(
            text(
                """
            SELECT (SELECT count(*) FROM journal_entries WHERE org_id = :org) AS entries,
                   (SELECT count(*) FROM postings WHERE org_id = :org) AS postings,
                   (SELECT count(*) FROM accounts WHERE org_id = :org) AS accounts,
                   (SELECT count(*) FROM transactions WHERE org_id = :org) AS transactions
            """
            ),
            {"org": org_id},
        )
        .mappings()
        .one()
    )
    summary = {
        "checks": per_check,
        "trial_balance": [_jsonable(dict(r)) for r in totals],
        "counts": _jsonable(dict(counts)),
        "errors": sum(per_check[name] for name, sev, _ in CHECKS if sev == "error"),
        "warnings": sum(per_check[name] for name, sev, _ in CHECKS if sev == "warning"),
    }
    return findings, summary


def run_reconciliation(session: Session, actor: Actor) -> ReconciliationRun:
    actor.require(Permission.RECONCILIATION_RUN)
    started_at = datetime.now(UTC)
    t0 = time.perf_counter()
    with session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        findings, summary = run_checks(session, actor.org_id)
    duration = int((time.perf_counter() - t0) * 1000)
    status = ReconciliationStatus.FAILED if summary["errors"] else ReconciliationStatus.PASSED
    with session.begin():
        run = ReconciliationRun(
            org_id=actor.org_id,
            status=status,
            summary=summary,
            findings=findings,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            started_at=started_at,
            duration_ms=duration,
        )
        session.add(run)
        session.flush()
        audit.record(
            session,
            actor,
            "reconciliation.run",
            target_type="reconciliation_run",
            target_id=run.id,
            metadata={"status": str(status), "errors": summary["errors"], "warnings": summary["warnings"]},
        )
    return run
