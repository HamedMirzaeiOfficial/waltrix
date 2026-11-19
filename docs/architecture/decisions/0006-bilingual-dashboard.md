# ADR 0006: A bilingual dashboard with English source text as keys

**English** · [فارسی](../../fa/architecture/decisions/0006-bilingual-dashboard.md)

**Status:** accepted

**Context.** The dashboard and the documentation must be usable in Persian and English. Persian is
right-to-left, uses its own digits and is usually read with the Solar Hijri calendar. The dashboard moves
money, so localisation must never change an amount, and switching language must never lose the state of
an operation whose outcome is still unknown.

**Decision.**

* Translatable text is wrapped in `t("English text")`; the English text is the key and
  `apps/web/src/locales/fa.json` holds the Persian. Strings built at module load are marked with `msg()`
  and translated when displayed. A missing translation falls back to readable English.
* The language is chosen in `index.html` before React loads (saved choice, else the browser language) and
  sets `<html lang dir>`. Switching remounts the UI below the React Query cache (`key={lang}`).
* A switch is refused while a money operation is pending or unknown (`useLanguageLock`), because the
  remount would discard the idempotency key the page needs to verify the outcome.
* Layout uses logical CSS (`ps-*`, `text-start`, `end-*`); amounts, ids and Latin names are isolated as
  left-to-right text. Numbers and dates use `Intl` with `fa-IR` (Persian digits, Solar Hijri calendar).
  Amounts typed with Persian digits are converted to ASCII before the SDK's string parser.
* `scripts/i18n-check.mjs` runs in CI and fails on missing translations, non-Persian entries and
  placeholder mismatches.
* The API stays English. Error **codes** are the contract and the dashboard translates by code.

**Rejected.** A library such as i18next or FormatJS: more capable (plurals, ICU messages), but Persian has
no plural forms that matter here and the remaining needs are covered by `Intl`. Opaque keys
(`transfer.posted.title`): an untranslated key would leak into the UI, and the code would be harder to
read. A context-based store that re-renders subscribers instead of remounting: no lock needed, but every
component and helper that formats text would have to subscribe.

**Consequences.** Changing English text changes its key, which the CI check catches. Values that reach the
UI at runtime (enum labels) must be listed with `msg()` in `format.ts`. Field validation messages from the
API remain English. The learning guide and the technical docs exist in both languages, with a shared
glossary (`docs/glossary.md`).
