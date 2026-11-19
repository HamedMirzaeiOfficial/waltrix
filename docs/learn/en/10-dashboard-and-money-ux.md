# Chapter 10 — The dashboard and the UX of moving money

**English** · [فارسی](../10-dashboard-and-money-ux.md)

Files for this chapter: `apps/web/src/features/transfer/{machine.ts,TransferPage.tsx}`, `lib/useIdempotentAction.ts`, `components/ui/data.tsx`, `index.css`, [design-system.md](../../design-system.md)

## 1. The worst sentence in a financial app

"Transfer completed successfully", when we do not know yet.

Most UIs have two states: success or error. But a network request really has **four** outcomes:

| Outcome | Meaning | What Waltrix says |
| --- | --- | --- |
| Definite success | the server said POSTED | "Transfer posted" (green) |
| Definite failure | the server said, for example, insufficient funds | "Transfer failed. No money moved." (red) |
| Rejected | the request was not executed (validation, permission) | "Request not accepted. Nothing was executed." (amber) |
| **Unknown** | no response arrived | "Result unknown" + automatic verification (amber) |

## 2. A pure state machine, separate from React

`machine.ts` is a pure reducer, with no React and no network:

```
edit ──REVIEW──► review ──SUBMIT──► submitting ──► success | failed | rejected | unknown
                                         ▲                                        │
                                         └──────────────VERIFY────────────────────┘
```

Rules enforced in the code:

- **The idempotency key is created when entering review** and stays the same for every submit/verify of that draft.
- **Editing discards the key**; new parameters need a new key (otherwise the server answers 409).
- `success` is reachable **only** from the `SUCCEEDED` event (a server response). There is no optimistic path.
- In `submitting`, the `SUBMIT` event is ignored.

Because the reducer is pure, testing it is painless (`machine.test.ts`): for example, `transferReducer(review, {type: "SUCCEEDED"})` returns the same `review`.

**Lesson:** separate workflow logic from the UI. React is for showing the state, not for defining it.

## 3. Preventing double submission, in two layers

1. The reducer ignores `SUBMIT` in `submitting`.
2. `inFlight` is a `useRef` checked in `execute`:

```ts
if (inFlight.current) return; // guards double submission even across fast clicks
inFlight.current = true;
```

Why a `ref` and not `state`? Because setState only applies on the next render; two clicks in one tick both see the old `state`. A ref changes immediately. In development StrictMode, React runs effects twice; the same ref blocks the second request too. And even if a second request did go out, it would carry the same key and the server would replay. Three layers for one click!

`TransferPage.test.tsx` fires two `fireEvent.click` in one tick and checks that `create` was called exactly once, even 300 ms after success.

## 4. Verify "unknown" automatically

```ts
useEffect(() => {
  if (state.kind !== "unknown" || state.attempt > AUTO_VERIFY_ATTEMPTS) return;
  const timer = setTimeout(() => dispatch({ type: "VERIFY" }), verifyDelayMs(state.attempt));
  return () => clearTimeout(timer);
}, [state]);
```

"Verify" means sending the **same** request again with the **same** key. Because the server is idempotent, this returns the original outcome and never moves money twice. Three attempts with delays of 1, 2 and 4 seconds, then a "Check again" button. And while the outcome is unknown, `beforeunload` warns the user not to close the page.

## 5. The review screen

Before sending, the user sees: the amount in large type, the name, `owner_reference` and short id of both wallets, and the "source balance after". A common mistake in money transfers is the wrong recipient with a similar name; the second identifier prevents it.

Client-side validation (amount format, more than the balance) is only for convenience. The Playwright test `an overspend is a confirmed failure` sends the bad request directly with `fetch` and shows that the server blocks it independently of the UI.

## 6. React Query: a mutation is never retried automatically

In `App.tsx`:

```ts
mutations: { retry: false },
queries: { retry: (count, err) => !(err instanceof WaltrixApiError && err.status < 500) && count < 1 },
```

Retries for financial operations happen only in the SDK and only with a key. If React Query retried as well, each attempt would be a new SDK call with a **new key**: exactly the bug we set out to avoid.

## 7. The design system

- **Tokens** live in `index.css` as CSS variables; Tailwind 4 turns them into classes like `bg-surface` and `text-muted` with `@theme inline`. The light theme only swaps the variables; no component has a hex colour.
- **Numbers** use `tabular` (equal-width digits) so amount columns line up.
- **A responsive table:** from one column definition, `DataTable` renders a `<table>` on desktop and stacked cards on mobile. (This caused an interesting bug in the Playwright tests; chapter 13.)
- **Accessibility:** Radix for focus and keyboard, `aria-live` for the result area, rows that activate with Enter, a "Skip to content" link, and `prefers-reduced-motion`.
- **Two languages:** the dashboard is in Persian and English, with a right-to-left layout, Persian digits and the Solar Hijri calendar. The details, and why switching language is locked during an unknown transfer, are in [chapter 15](15-i18n.md).

## Exercises

1. In `machine.ts`, allow `EDIT` from the `unknown` state too. Why is that dangerous? Write a scenario in which the user sends money twice.
2. Remove `inFlight` and keep StrictMode on. Count the requests in the browser's network panel. Why does the money still not move twice?
3. Apply the `useIdempotentAction` pattern to the "Run reconciliation" button. Is it needed? (Hint: does running reconciliation again do any harm?)
4. Design a real "pending" state: if transfers ever become asynchronous (the server returns 202 and a PENDING status), the UI must follow the status by polling. Extend the machine.
