# فصل ۱۲ — عملیات و استقرار

فایل‌های این فصل: `apps/api/src/waltrix_api/{observability,ratelimit,cli}.py`، `routers/operations.py` (health)، `Dockerfile`، `docker-compose.yml`، `.github/workflows/ci.yml`، [deployment.md](../deployment.md)

## ۱. correlation id: نخ تسبیح

`RequestContextMiddleware` برای هر درخواست یک `correlation_id` می‌سازد (یا اگر کلاینت `X-Correlation-ID` معتبر فرستاده، همان را برمی‌دارد) و در یک `ContextVar` می‌گذارد. همین id در این‌ها هست:

- هر خط لاگ JSON
- هدر پاسخ
- بدنه‌ی هر خطا
- رویداد audit
- ردیف تراکنش و سند journal

یعنی از یک شکایت مشتری («این خطا را دیدم: 4f2c...») مستقیم به لاگ، به رویداد audit و به سند مالی همان درخواست می‌رسید. id ورودی با regex `^[A-Za-z0-9._-]{1,64}$` محدود شده؛ وگرنه کلاینت می‌توانست متن دلخواه (حتی HTML) در لاگ‌ها تزریق کند (`test_correlation_id_propagates`).

## ۲. middleware خالص ASGI

middleware با `BaseHTTPMiddleware` نوشته نشده، بلکه به‌شکل ASGI خالص (`__call__(scope, receive, send)`). دلیل: ساده‌تر است، با streaming مشکل ندارد، و `ContextVar` را درست در محدوده‌ی درخواست نگه می‌دارد. با پیچیدن `send` کد وضعیت پاسخ گرفته می‌شود و هدرهای امنیتی اضافه می‌شوند.

## ۳. متریک‌ها

```python
OPERATIONS = Counter("waltrix_financial_operations_total", "...", ["operation", "outcome"])
OPERATION_LATENCY = Histogram("waltrix_financial_operation_duration_seconds", "...", ["operation"])
```

نکته‌ی معماری: هسته (`waltrix_core`) به prometheus وابسته نیست. `runner.py` یک لیست `OBSERVERS` دارد و API یک تابع در آن ثبت می‌کند. اگر observer خطا بدهد، فقط لاگ می‌شود:

```python
except Exception:  # observers must never break money movement
```

**درس:** مشاهده‌پذیری هرگز نباید بتواند عملیات اصلی را بشکند.

label متریک `route` الگوی مسیر است (`/api/v1/wallets/{wallet_id}`)، نه مسیر واقعی. اگر id واقعی label شود، هر کیف پول یک سری زمانی جدید می‌سازد و Prometheus منفجر می‌شود (cardinality explosion).

## ۴. liveness در برابر readiness

| probe | سؤال | چه چیزی را چک می‌کند |
| --- | --- | --- |
| `/healthz` | پروسه زنده است؟ | هیچ؛ فقط جواب می‌دهد |
| `/readyz` | می‌تواند ترافیک بگیرد؟ | دیتابیس جواب می‌دهد **و** migration اعمال شده |

اگر liveness دیتابیس را هم چک کند، با یک قطعی کوتاه دیتابیس، Kubernetes همه‌ی podها را restart می‌کند و مشکل را بدتر می‌کند. readiness فقط pod را از load balancer خارج می‌کند.

## ۵. کارهای پس‌زمینه بدون Celery

| دستور | کار | چرا امن است چند بار هم‌زمان اجرا شود |
| --- | --- | --- |
| `waltrix expire-holds` | انقضای هولدها | `SKIP LOCKED`، هر هولد یک تراکنش |
| `waltrix purge-idempotency` | پاک کردن کلیدهای منقضی | DELETE شرطی |
| `waltrix reconcile` | تطبیق همه‌ی سازمان‌ها | فقط‌خواندنی؛ exit code غیرصفر یعنی مشکل |

هر سه idempotent هستند؛ یک cron یا یک حلقه‌ی ساده (`worker` در compose) کافی است. صف پیام وقتی لازم است که کار طولانی، توزیع‌شده یا رویدادمحور داشته باشید.

## ۶. اجرای پشت پروکسی با پیشوند مسیر

در سرور مشترک، پیش‌نمایش از آدرسی مثل `/shared/ide/proxy/4820/` باز می‌شود و پروکسی پیشوند را **حذف** می‌کند. سه چیز باید پیشوند را بدانند:

1. assetهای Vite: `VITE_BASE=/shared/ide/proxy/4820/` در زمان build.
2. React Router: `basename={import.meta.env.BASE_URL}`.
3. کوکی: `WALTRIX_SESSION_COOKIE_PATH=/shared/ide/proxy/4820/api`، چون مرورگر مسیر **عمومی** را می‌بیند.

و API می‌تواند خود build داشبورد را serve کند (`WALTRIX_WEB_DIST`) تا همه چیز یک origin باشد: بدون CORS، کوکی ساده.

## ۷. Docker و CI

`Dockerfile` چندمرحله‌ای است: مرحله‌ی Node داشبورد را build می‌کند، مرحله‌ی Python فقط نتیجه را کپی می‌کند. کاربر غیر root و `HEALTHCHECK` روی `/readyz`. صادقانه: Docker در محیط توسعه‌ی این پروژه موجود نبود و این فایل‌ها فقط در CI build می‌شوند.

CI چهار job دارد: پایتون روی PostgreSQL 16 و 17 (ماتریس)، Node (lint، typecheck، تست، build)، Playwright، و build تصویر Docker.

## ۸. backup، RPO و RTO

- **RPO** (چقدر داده می‌توانیم از دست بدهیم): با archive کردن WAL، به اندازه‌ی تأخیر ارسال WAL؛ صفر فقط با replication همگام.
- **RTO** (چقدر طول می‌کشد برگردیم): زمان restore و replay کردن WAL.
- بعد از restore، **قبل** از باز کردن ترافیک، `waltrix reconcile` باید سبز باشد.
- نکته‌ی زیبا: کلاینت‌هایی که کلید idempotency خود را نگه داشته‌اند، می‌توانند درخواست‌های گم‌شده بعد از نقطه‌ی بازیابی را با خیال راحت دوباره بفرستند.

## تمرین‌ها

1. API را اجرا کنید، چند انتقال بزنید و `curl localhost:4820/metrics | grep financial` را ببینید. یک انتقال ناموفق بزنید و تغییر counter را پیدا کنید.
2. یک observer جدید بنویسید که برای عملیات کندتر از ۵۰۰ میلی‌ثانیه هشدار لاگ کند. آن را در `create_app` ثبت کنید.
3. با `pg_dump` از دیتابیس dev backup بگیرید، در یک دیتابیس جدید restore کنید، و `waltrix reconcile` را روی آن اجرا کنید.
4. داشبورد را با `VITE_BASE` درست build کنید و از آدرس پیش‌نمایش سرور مشترک باز کنید. اگر ورود کار نکرد، از DevTools ببینید کوکی با چه path ثبت شده.
