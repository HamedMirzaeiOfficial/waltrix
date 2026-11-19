# REST API v1

[English](../../api/rest.md) · **فارسی**

مسیر پایه `/api/v1`. مستندات تعاملی در `/api/docs` و schema ماشین‌خوان در `/api/v1/openapi.json`.

## قراردادها

* **احراز هویت.** سرورها: `Authorization: Bearer wtx_key_...` (کلید به یک سازمان و نقش گره خورده). داشبورد:
  کوکی session از نوع httpOnly + `X-Waltrix-Organization: <org id>` + `X-Requested-With: waltrix-web` برای نوشتن.
* **پول.** `{"amount": 1250, "currency": "USD"}`. `amount` یک عدد صحیح مثبت JSON به واحد خرد است،
  ≤ 2^53−1. `10.5`، `"10"` و `true` رد می‌شوند (422).
* **Idempotency.** روی هر مسیری که پول جابه‌جا می‌کند اجباری است: `Idempotency-Key: <1 تا 255 نویسه‌ی قابل چاپ>`.
  replay هدر `Idempotent-Replayed: true` دارد.
* **Correlation.** `X-Correlation-ID` (`[A-Za-z0-9._-]{1,64}`) بفرستید یا یکی ساخته‌شده بگیرید؛ در هر پاسخ، خط
  لاگ، رویداد حسابرسی، تراکنش و سند هست.
* **صفحه‌بندی.** بر اساس cursor: `?limit=1..100&cursor=...` ←
  `{"data": [...], "next_cursor": "...", "has_more": true}`. حتی وقتی ردیف تازه درج می‌شود پایدار است.
* **زبان.** پاسخ‌ها و پیام‌ها انگلیسی‌اند. کلاینت‌ها بر اساس `code` ثابت خطا بومی‌سازی می‌کنند، نه متن `message`؛
  داشبورد فارسی دقیقاً همین کار را می‌کند.
* **خطاها.**

```json
{"error": {"code": "insufficient_funds", "message": "insufficient available balance",
           "details": {"transaction_id": "0b9e..."}, "correlation_id": "4f2c..."}}
```

| status | کدها |
| --- | --- |
| 400 | `organization_required` |
| 401 | `authentication_failed` |
| 403 | `permission_denied`، `csrf_failed`، `user_session_required` |
| 404 | `not_found` (برای منابع مستأجرهای دیگر هم) |
| 409 | `idempotency_key_reused`، `concurrent_request`، `invalid_state_transition`، `conflict` |
| 422 | `validation_failed`؛ کسب‌وکاری: `insufficient_funds`، `wallet_not_active`، `currency_mismatch`، `same_wallet`، `hold_not_active`، `hold_expired`، `capture_exceeds_hold`، `not_reversible`، `reversal_exceeds_remaining` |
| 429 | `rate_limited` (+ `Retry-After`) |
| 500 | `internal_error` (بدون نشت جزئیات داخلی) |

## endpointها

| method و مسیر | مجوز | نکته |
| --- | --- | --- |
| `POST /auth/register`، `POST /auth/login`، `POST /auth/logout`، `GET /auth/me` | - | session داشبورد |
| `GET/POST /organizations` | session کاربر | فهرست عضویت‌ها / ساخت (سازنده مالک می‌شود) |
| `GET/PATCH /organizations/current` | خواندن / `org:manage` | |
| `GET/POST /organizations/current/members`، `PATCH/DELETE .../{id}` | `members:read` / `members:manage` | نقش بالاتر از خود ممنوع؛ آخرین مالک محافظت‌شده |
| `GET/POST /api-keys`، `POST /api-keys/{id}/revoke`، `POST /api-keys/{id}/rotate` | `api_keys:manage` (فقط کاربر) | راز فقط یک بار برمی‌گردد |
| `GET/POST /wallets`، `GET /wallets/{id}`، `GET /wallets/{id}/balance` | `wallets:read` / `wallets:manage` | فیلتر: `status`، `currency`، `search` |
| `POST /wallets/{id}/suspend` · `/activate` · `/close` | `wallets:manage` | |
| `POST /wallets/{id}/credit` · `/debit` | `money:fund` | منبع تأمین **شبیه‌سازی‌شده**، Idempotency-Key |
| `GET /wallets/{id}/statement` | `ledger:read` | موجودی جاری از سطرها، `start`/`end` |
| `POST /transfers`، `GET /transfers/{id}` | `money:move` | Idempotency-Key |
| `GET /transactions`، `GET /transactions/{id}` | `ledger:read` | فیلتر: `status`، `type`، `wallet_id`، `currency`، `created_after/before`، `search`، `sort` |
| `GET/POST /holds`، `GET /holds/{id}`، `POST /holds/{id}/capture` · `/release` | `money:move` | Idempotency-Key |
| `POST /reversals` | `money:reverse` | کامل یا جزئی (`amount`) |
| `GET /accounts`، `POST /accounts`، `GET /accounts/{id}`، `GET /accounts/{id}/statement` | `ledger:read` / `accounts:manage` | فقط حساب داخلی با POST |
| `GET /journal-entries`، `GET /journal-entries/{id}` | `ledger:read` | فیلتر: `kind`، `phase`، `account_id` |
| `POST /journal-entries` | `ledger:manual_entry` | تراز، فقط حساب‌های داخلی غیرکیف پول |
| `POST/GET /reconciliation/runs`، `GET /reconciliation/runs/{id}` | `reconciliation:run` / `:read` | |
| `GET /audit-events` | `audit:read` | فیلتر: پیشوند `action`، `target_id`، `actor_id` |
| `GET /overview` | `ledger:read` | متریک‌های داشبورد از ردیف‌های واقعی |
| `GET /currencies` | - | کدها و توان‌های پشتیبانی‌شده |
| `GET /healthz`، `GET /readyz`، `GET /metrics` | - | liveness، readiness (دیتابیس + migration)، Prometheus |

برای داده‌ی مالی هیچ endpoint عمومی CRUD وجود ندارد: موجودی‌ها فقط از طریق عملیات بالا تغییر می‌کنند.

## مثال

```bash
KEY=wtx_key_...   # از `waltrix seed-demo` یا داشبورد
curl -s -X POST http://127.0.0.1:4820/api/v1/transfers \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-81-payment" \
  -d '{"source_wallet_id":"<uuid>","destination_wallet_id":"<uuid>","amount":1250,"currency":"USD"}'
```

```json
{"id": "9cd10db6-...", "type": "transfer", "status": "posted", "amount": 1250, "posted_amount": 1250,
 "reversed_amount": 0, "currency": "USD", "source_wallet_id": "...", "destination_wallet_id": "...",
 "correlation_id": "4f2c...", "created_at": "2026-11-19T15:01:12.117Z", "posted_at": "2026-11-19T15:01:12.117Z", ...}
```

فرستادن دوباره‌ی همان درخواست، همان body را با `Idempotent-Replayed: true` برمی‌گرداند. عوض کردن مبلغ با همان
کلید `409 idempotency_key_reused` می‌دهد.
