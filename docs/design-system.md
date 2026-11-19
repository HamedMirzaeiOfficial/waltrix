# Design system

**English** · [فارسی](fa/design-system.md)

The dashboard aims for a calm, dense, trustworthy financial tool: dark-first, with a light theme of equal
quality, indigo used sparingly for intent, and numbers that are easy to scan.

## Tokens

Defined once in `apps/web/src/index.css` as CSS variables and exposed to Tailwind 4 through `@theme inline`.
Components use semantic utilities (`bg-surface`, `text-muted`, `border-border`) and never raw hex values,
so themes switch by changing variables only (`<html data-theme="dark|light">`, persisted in localStorage).

| Token | Dark | Light | Use |
| --- | --- | --- | --- |
| `--bg` | `#0F1117` | `#F6F7F9` | page |
| `--sidebar` | `#151922` | `#FFFFFF` | navigation |
| `--surface` / `--surface-2` | `#1D2330` / `#232A39` | `#FFFFFF` / `#F3F4F7` | cards / inputs, chips |
| `--border` | `#2B3342` | `#E4E7EC` | hairlines |
| `--primary` | `#818CF8` | `#4F46E5` | primary action, focus, active nav |
| `--text` / `--muted` | `#F3F4F6` / `#9CA3AF` | `#101828` / `#667085` | content / secondary |
| `--success`, `--danger`, `--warning`, `--info` | emerald, red, amber, blue | darker variants | statuses only |

Each status color has a `-soft` translucent background for badges and banners. Light-theme colors are
darker so text contrast meets WCAG AA on white.

## Typography

Inter Variable for UI (with `cv11`, `ss01` for clearer digits), JetBrains Mono Variable for identifiers,
keys and codes. Money uses the `tabular` utility (tabular figures) so columns align. Page titles 22px
semibold with tight tracking; table headers 12px uppercase with wide tracking in the faint color.

## Components

`components/ui/` contains a small shadcn-style kit built on Radix primitives (accessible focus management,
keyboard support, portals): Button (`primary`, `secondary`, `ghost`, `outline`, `danger`, `danger-soft`),
Input, Field (label + error with `role="alert"`), Card, Badge, StatusBadge, Skeleton (shimmer), Dialog,
ConfirmDialog (cannot be dismissed while pending), Select, Tabs, Tooltip, Toast, DataTable, Pager,
EmptyState, ErrorState, ErrorBoundary, CopyId, Money.

**DataTable** renders a semantic table on `md+` and stacked cards on small screens from the same column
definitions; rows are focusable and activate with Enter/Space.

## Money UX rules

1. Parse user input as a decimal string into minor units; reject more decimals than the currency allows.
   Persian digits are converted to ASCII first.
2. Show a review step with names, owner references and short ids for both sides before any transfer.
3. Disable and guard submission while pending; one idempotency key per attempt, reused for verification.
4. Four visibly different outcomes: confirmed success (green), confirmed failure (red, "no money moved"),
   not accepted (amber, "nothing executed"), unknown (amber, verify). Never optimistic success.
5. "Simulated funding" is labelled wherever deposits and withdrawals appear.

## Two languages and right-to-left

The dashboard runs in English and Persian (see [ADR 0006](architecture/decisions/0006-bilingual-dashboard.md)
and chapter 15 of the learning guide). Rules for components:

* Never hard-code UI text: wrap it in `t("…")`, or `msg("…")` for constant tables, and add the Persian
  entry to `src/locales/fa.json`. `npm run i18n:check -w @waltrix/web` fails otherwise.
* Use logical spacing and alignment (`ps-*`, `pe-*`, `ms-*`, `start-*`, `end-*`, `text-start`,
  `text-end`, `border-e`), never `left`/`right` variants, except for centred overlays.
* Mirror directional icons (arrows, chevrons) with `rtl:-scale-x-100`; leave symmetric icons alone.
* Amounts go through `formatMoney`/`<Money>`, which isolate them as left-to-right text so a sign never
  jumps to the wrong side. Ids and codes use `font-mono` (isolated in RTL). User-entered names get
  `dir="auto"`; emails `dir="ltr"`.
* Persian uses Vazirmatn Variable (Inter has no Persian glyphs); digits and dates come from `Intl` with
  `fa-IR`, which also gives the Solar Hijri calendar.
* Charts keep a left-to-right time axis in both languages.

## Motion and accessibility

Short fade-up transitions (240 ms), skeletons instead of spinners for content, `prefers-reduced-motion`
disables animation. Skip link, visible focus rings, labelled controls, `aria-live` outcome regions, and
charts paired with textual values (the status distribution lists counts and percentages).
