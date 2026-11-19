# استقرار و عملیات

[English](../deployment.md) · **فارسی**

## شکل کلی

یک image (`Dockerfile`): اپ FastAPI که API و build داشبورد را از یک origin سرو می‌کند، به‌علاوه‌ی همان image
که به‌عنوان worker نگهداری اجرا می‌شود. PostgreSQL تنها وابستگی دارای state است.

```bash
docker compose up --build          # db + migrate + api (127.0.0.1:8080) + worker
docker compose run --rm api waltrix seed-demo   # داده‌ی ساختگی، اختیاری
```

> Dockerfile و فایل Compose ارائه شده‌اند و در CI build می‌شوند، ولی **در محیط توسعه‌ی این مخزن اجرا نشده‌اند**
> (Docker آن‌جا در دسترس نبود). مسیر بدون Docker در پایین همان است که از ابتدا تا انتها اجرا و آزموده شد.

## بدون Docker

```bash
scripts/dev-db.sh                                   # PostgreSQL خصوصی روی 127.0.0.1:4822
python -m venv .venv && .venv/bin/pip install -e packages/ledger-core -e "apps/api[dev]" -e packages/python-sdk
npm ci && npm run build -w @waltrix/sdk && npm run build -w @waltrix/web
export WALTRIX_DATABASE_URL=postgresql://waltrix@127.0.0.1:4822/waltrix
.venv/bin/waltrix migrate
WALTRIX_WEB_DIST=apps/web/dist .venv/bin/waltrix serve --port 4820
```

پشت یک reverse proxy که اپ را زیر یک پیشوند مسیر (`/some/prefix/`) سرو می‌کند، داشبورد را با
`VITE_BASE=/some/prefix/` build کنید و `WALTRIX_SESSION_COOKIE_PATH=/some/prefix/api` و
`WALTRIX_COOKIE_SECURE=true` را تنظیم کنید.

## چک‌لیست production

* `WALTRIX_ENVIRONMENT=production` (کوکی `Secure` را اجباری می‌کند)، فقط HTTPS، و `WALTRIX_TRUSTED_PROXY_COUNT`
  برابر تعداد واقعی پروکسی‌ها.
* نقش‌های جدای دیتابیس برای migration (مالک) و اجرا (فقط DML). TLS تا دیتابیس.
* `waltrix migrate` را به‌شکل یک job یک‌باره قبل از شروع نسخه‌های تازه‌ی API اجرا کنید (migrationها در
  production فقط رو به جلو هستند؛ `downgrade` برای توسعه است).
* زمان‌بندی کنید: `waltrix expire-holds` (هر دقیقه)، `waltrix purge-idempotency` (ساعتی) و
  `waltrix reconcile` (ساعتی یا شبانه؛ با یافته exit غیرصفر → هشدار).
* `/metrics` را جمع‌آوری کنید؛ `/healthz` (liveness) و `/readyz` (دیتابیس در دسترس + schema اعمال‌شده) را probe کنید.

## مشاهده‌پذیری

| سیگنال | کجا |
| --- | --- |
| لاگ دسترسی JSON با correlation id، الگوی route، status، مدت | stdout |
| `waltrix_http_requests_total`، `waltrix_http_request_duration_seconds` | `/metrics` |
| `waltrix_financial_operations_total{operation,outcome}` (succeeded، failed، replayed، error) | `/metrics` |
| `waltrix_financial_operation_duration_seconds{operation}` (زمان داخل تراکنش دیتابیس) | `/metrics` |
| `waltrix_financial_operation_failures_total{operation,kind}` | `/metrics` |
| `waltrix_reconciliation_last_errors` | `/metrics` (با اجراهای API تنظیم می‌شود) |
| چه کسی چه کرد | جدول `audit_events` / `GET /audit-events` |

کارهای پس‌زمینه دستورات ساده و idempotent هستند؛ دید ما به آن‌ها از exit code، خط‌های لاگ، رویدادهای حسابرسی
(انقضای رزرو، تطبیق) و هشدار `overdue_hold` در تطبیق (اگر انقضا عقب بیفتد) است. متریک‌ها به ازای هر پروسه‌اند
(Prometheus آن‌ها را بین replicaها جمع می‌زند).

## Backup و بازیابی

* **Backup:** آرشیو پیوسته‌ی WAL + base backup دوره‌ای (مثلاً pgBackRest، یا point-in-time recovery یک
  دیتابیس مدیریت‌شده). `pg_dump` منطقی برای نصب‌های کوچک و تست کافی است.
* **RPO:** برابر تأخیر ارسال WAL (با streaming یا آرشیو چند ثانیه، صفر فقط با replication همگام).
  **RTO:** زمان restore کردن base backup و replay کردن WAL.
* **روال بازیابی:** restore روی یک instance تازه ← `waltrix migrate` (اگر به‌روز باشد کاری نمی‌کند) ← اجرای
  `waltrix reconcile` و الزام به موفق بودنش ← انتقال ترافیک. تراکنش‌هایی که بعد از نقطه‌ی بازیابی commit
  شده‌اند گم می‌شوند؛ کلاینت‌هایی که هنوز کلید idempotency خود را دارند می‌توانند با خیال راحت دوباره بفرستند.
* **بازیابی را مرتب تست کنید**؛ backup‌ای که هرگز restore نشده، امید است، نه backup.
