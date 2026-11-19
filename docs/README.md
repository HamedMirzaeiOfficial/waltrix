# Waltrix documentation

**English** · [فارسی](fa/README.md)

| Document | What it covers |
| --- | --- |
| [Architecture overview](architecture/overview.md) | layers, a transfer end to end, why a monolith, repository map |
| [Decision records](architecture/decisions/) | ADR 0001-0006: the ledger core, integer money, locking, idempotency, holds, bilingual dashboard |
| [Double-entry model](financial-model/double-entry.md) | entities, account types, how each operation posts, a worked example |
| [Lifecycles](financial-model/transaction-lifecycle.md) | transaction, hold and wallet state machines; what each HTTP outcome means |
| [Invariants](financial-model/invariants.md) | the 12 rules, where each is enforced, SQL to check them by hand |
| [Concurrency](concurrency.md) | the transaction boundary, lock order, race scenarios, idempotency, retries |
| [Reconciliation](reconciliation.md) | the checks, snapshots, scheduling, handling findings |
| [Security](security.md) | tenancy, authentication, authorization, CSRF, known gaps |
| [REST API](api/rest.md) | conventions, error codes, endpoints, examples |
| [Deployment](deployment.md) | Docker and non-Docker, production checklist, observability, backups |
| [Design system](design-system.md) | tokens, typography, components, money UX rules, RTL |
| [Glossary](glossary.md) | every term in English and Persian, with the dashboard label |
| [Learning guide](learn/en/README.md) | 15 chapters for study, with exercises and bug stories ([فارسی](learn/README.md)) |
