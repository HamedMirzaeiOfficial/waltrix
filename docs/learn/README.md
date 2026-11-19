# راهنمای یادگیری Waltrix (والتریکس)

> **Wallet + Matrix** — حسِ ساختار، تراکنش و تکنولوژی مالی.

این راهنما برای **مطالعه** نوشته شده، نه برای مرجع سریع. هدفش این است که با خواندن کد واقعی همین پروژه، مهندسیِ نرم‌افزارهای مالی را عمیق یاد بگیرید: حسابداری دوطرفه، تراکنش دیتابیس، قفل و همزمانی، idempotency، طراحی API و SDK، و UX عملیاتی که در آن «اشتباه» یعنی گم‌شدن پول.

> مرجع فنی دقیق (انگلیسی) در [`docs/`](../) است: [معماری](../architecture/overview.md)، [مدل دوطرفه](../financial-model/double-entry.md)، [ناوردایی‌ها](../financial-model/invariants.md)، [همزمانی](../concurrency.md)، [API](../api/rest.md)، [امنیت](../security.md).

## پیش‌نیاز

- Python و مقدمات SQL (`SELECT`، `JOIN`، تراکنش)
- TypeScript و مقدمات React (component، hook، state)
- آشنایی با HTTP و Git

لازم نیست حسابداری، SQLAlchemy، FastAPI، Hypothesis یا Playwright بلد باشید؛ در فصل‌ها توضیح داده می‌شوند.

## فصل‌ها

| # | فصل | موضوع اصلی |
| --- | --- | --- |
| ۱ | [نقشه‌ی معماری](01-architecture.md) | monorepo، لایه‌ها، چرا یک «هسته‌ی مالی» جدا |
| ۲ | [پول و حسابداری دوطرفه](02-money-and-double-entry.md) | واحد خرد، نوع حساب، بدهکار/بستانکار، چرا float ممنوع است |
| ۳ | [موتور ثبت و قیدهای دیتابیس](03-posting-engine.md) | `post_entry`، CHECK، FK ترکیبی، trigger تأخیری |
| ۴ | [تراکنش، قفل و همزمانی](04-transactions-and-locks.md) | READ COMMITTED، `FOR UPDATE`، ترتیب قفل، deadlock |
| ۵ | [Idempotency: تکرار امن](05-idempotency.md) | کلید، fingerprint، ثبت هم‌زمان با نتیجه، «نتیجه‌ی نامعلوم» |
| ۶ | [هولد، برگشت و چرخه‌ی وضعیت](06-holds-reversals-lifecycle.md) | ثبت pending، capture جزئی، reversal، state machine |
| ۷ | [تطبیق و حسابرسی](07-reconciliation-and-audit.md) | بازسازی از دفتر روزنامه، snapshot، audit log |
| ۸ | [امنیت و چندمستأجری](08-security-and-tenancy.md) | tenant، نقش و مجوز، API key، CSRF، enumeration |
| ۹ | [طراحی API و SDK](09-api-and-sdks.md) | خطای ساختاریافته، صفحه‌بندی cursor، retry امن، ParamSpec |
| ۱۰ | [داشبورد و UX عملیات مالی](10-dashboard-and-money-ux.md) | state machine انتقال، جلوگیری از ارسال دوباره، design token |
| ۱۱ | [تست](11-testing.md) | تست روی PostgreSQL واقعی، property-based، stress، Playwright |
| ۱۲ | [عملیات و استقرار](12-operations.md) | لاگ ساختاریافته، متریک، health/ready، backup و RPO |
| ۱۳ | [درس‌های باگ‌ها](13-bug-stories.md) | باگ‌ها و اشتباه‌های واقعیِ ساخت همین پروژه |

## مسیر پیشنهادی مطالعه

1. فصل ۱ را بخوانید و پروژه را با Quick start در [README](../../README.md) اجرا کنید. با کاربر دمو وارد شوید، یک انتقال بزنید و صفحه‌ی journal entry آن را ببینید.
2. فصل ۲ و ۳ را با هم بخوانید؛ کنارش `packages/ledger-core/src/waltrix_core/rules.py` و `services/ledger.py` را باز کنید.
3. فصل ۴ و ۵ قلب پروژه‌اند. بعد از خواندنشان `tests/concurrency/test_concurrency.py` را اجرا کنید.
4. فصل‌های ۶ تا ۹ را به ترتیب بخوانید.
5. فصل ۱۰ (فرانت) و ۱۱ (تست) را بخوانید و یک تست را عمداً بشکنید.
6. فصل ۱۳ را آخر بخوانید؛ بعد از دیدن کد، داستان باگ‌ها معنای بیشتری دارد.

هر فصل با چند **تمرین** تمام می‌شود. تمرین‌ها را واقعاً انجام دهید؛ بیشترین یادگیری همان‌جاست.

## نحوه‌ی خواندن کد

- **از ناوردایی‌ها (invariants) شروع کنید، نه از جزئیات.** اول جدول [invariants.md](../financial-model/invariants.md) را ببینید: هر قانون کجا در موتور، کجا در دیتابیس، کجا در reconciliation و با کدام تست چک می‌شود.
- **مسیر یک درخواست را دنبال کنید.** «انتقال پول» را از دکمه‌ی Confirm در `apps/web/src/features/transfer/TransferPage.tsx` تا `routers/money.py::create_transfer`، `services/operations.py::transfer` و `services/runner.py::run_operation` دنبال کنید.
- **تست‌ها مستندات اجرایی‌اند.** وقتی نمی‌دانید یک تابع دقیقاً چه تضمینی می‌دهد، تستش را بخوانید.

## واژه‌نامه‌ی کوتاه

| اصطلاح | معنی در این پروژه |
| --- | --- |
| Ledger / دفتر کل | مجموعه‌ی حساب‌های یک سازمان |
| Journal entry / سند | یک رویداد مالی با چند سطر بدهکار و بستانکار؛ تغییرناپذیر |
| Posting / سطر سند | یک بدهکار یا بستانکار روی یک حساب |
| Debit / Credit | بدهکار / بستانکار (سمت چپ / راست دفتر) |
| Minor unit / واحد خرد | سنت برای دلار؛ همه‌ی مبلغ‌ها عدد صحیح به این واحدند |
| Hold / رزرو | پولی که کنار گذاشته شده ولی هنوز منتقل نشده |
| Reversal / برگشت | سند معکوس برای اصلاح؛ سند اصلی پاک نمی‌شود |
| Idempotency | اجرای چندباره‌ی یک درخواست، فقط یک‌بار اثر داشته باشد |
| Reconciliation / تطبیق | بازسازی موجودی‌ها از دفتر روزنامه و مقایسه با مقادیر ذخیره‌شده |
| Tenant / مستأجر | یک سازمان با داده‌ی کاملاً جدا |
