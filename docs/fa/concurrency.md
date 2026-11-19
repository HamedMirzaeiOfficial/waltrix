# همزمانی، idempotency و بازیابی از خطا

[English](../concurrency.md) · **فارسی**

## مرز تراکنش

هر تغییر مالی یک فراخوانی `runner.run_operation` است که یک تراکنش PostgreSQL در اختیار دارد:

```
BEGIN (READ COMMITTED)
  SET LOCAL lock_timeout = '5s'
  claim idempotency key              -- INSERT ... ON CONFLICT DO NOTHING
  SAVEPOINT
    lock rows in global order, validate, insert entry + postings, update balances
  on BusinessRuleViolation: ROLLBACK TO SAVEPOINT, insert FAILED transaction
  complete idempotency record
COMMIT                                -- deferred triggers re-check every entry balances
```

commit جزئی غیرممکن است: فقط یک COMMIT وجود دارد. اگر پروسه در هر نقطه‌ای قبل از آن crash کند، چیزی باقی
نمی‌ماند (PostgreSQL با قطع اتصال، تراکنش باز را rollback می‌کند).

## ترتیب قفل (بدون deadlock)

```
کلید idempotency  →  ردیف تراکنش / رزرو  →  کیف پول‌ها FOR SHARE (به ترتیب id)  →  حساب‌ها FOR UPDATE (به ترتیب id)
```

* حساب‌ها قبل از `SELECT ... FOR UPDATE` بر اساس id مرتب می‌شوند، پس A→B و B→A هر دو اول `min(A, B)` را
  قفل می‌کنند؛ یکی فقط منتظر می‌ماند. `test_opposite_transfers_do_not_deadlock` چهل انتقال از این نوع را
  هم‌زمان اجرا می‌کند.
* کیف پول‌ها `FOR SHARE` می‌گیرند: انتقال‌های هم‌زمان روی ردیف کیف پول همدیگر را نمی‌بندند، ولی تغییر وضعیت
  (`FOR UPDATE`) منتظر جابه‌جایی‌های در جریان می‌ماند، پس کیف پول نمی‌تواند وسط یک انتقال تعلیق شود.
* موجودی‌ها بعد از گرفتن قفل خوانده می‌شوند (`populate_existing=True`)، پس بررسی منفی شدن همیشه آخرین مقدار
  commit‌شده را می‌بیند.

## جدول سناریوها

| سناریو | چه اتفاقی می‌افتد | اثبات |
| --- | --- | --- |
| ۴۰ برداشت ۱۰۰ دلاری هم‌زمان از کیف پول ۱۰۰۰ دلاری | دقیقاً ۱۰ موفق، ۳۰ با `insufficient_funds` ناموفق، موجودی صفر | `test_concurrent_debits_cannot_overspend` |
| رزرو و انتقال در رقابت برای همان وجه | `floor(1000/150) = 6` موفق، قابل استفاده هرگز منفی نمی‌شود | `test_concurrent_holds_and_transfers_respect_available` |
| ۲۵ درخواست با یک Idempotency-Key | ۱ اجرا، ۲۴ همان تراکنش را replay می‌کنند | `test_same_idempotency_key_concurrently_executes_once` |
| نهایی‌سازی در برابر آزادسازی همان رزرو | برای هر رزرو دقیقاً یکی برنده است | `test_capture_and_release_race_has_one_winner` |
| ۶ worker انقضا به‌طور موازی | هر رزرو یک بار منقضی می‌شود | `test_parallel_expiry_workers_never_double_release` |
| ۱۲ بازپرداخت جزئی ۱۰۰ تایی هم‌زمان روی انتقال ۵۰۰ | دقیقاً ۵ موفق | `test_reversal_race_cannot_double_refund` |
| پروسه بعد از flush شدن سطرها «می‌میرد» | چیزی commit نمی‌شود؛ تلاش دوباره با همان کلید یک بار موفق می‌شود | `test_3_failure_mid_operation_commits_nothing` |
| ۱۶ thread × ۳۰ عملیات تصادفی روی ۶ کیف پول هم‌پوشان، هر انتقال تکرار می‌شود | پول حفظ می‌شود، موجودی منفی نیست، reconciliation موفق است | `test_stress_random_operations_preserve_invariants` |

نمونه‌ی خروجی آخرین تست از یک اجرای محلی (اعداد با تصادف و زمان‌بندی فرق می‌کنند):
`stress: {'succeeded': 455, 'failed': 11} external={'in': 16093, 'out': 13486} entries={'entries': 439, ...}`.
این یک تست درستی است، نه benchmark؛ هیچ ادعایی درباره‌ی توان عملیاتی نمی‌شود.

## قواعد idempotency

* محدوده: `(سازمان، عملیات، کلید)`. همان کلید روی `transfer.create` و `wallet.credit` مستقل‌اند.
* اثر انگشت: SHA-256 از JSON استاندارد نام عملیات و پارامترهای اعتبارسنجی‌شده‌اش. همان کلید + همان اثر
  انگشت → replay. همان کلید + اثر انگشت دیگر → `409 idempotency_key_reused`.
* همزمانی: INSERT دوم روی ایندکس یکتا منتظر تراکنش اول می‌ماند. اگر آن commit شود، INSERT ما کاری نمی‌کند و
  replay می‌کنیم؛ اگر rollback شود، ما به‌عنوان نویسنده‌ی اول ادامه می‌دهیم.
* نتیجه‌های ذخیره‌شده: موفقیت (ارجاع به منبع) و شکست‌های قطعی کسب‌وکاری (کد خطا و شناسه‌ی تراکنش FAILED).
  ذخیره‌نشده: خطای اعتبارسنجی، خطای احراز هویت، crash؛ این‌ها کلید را آزاد می‌گذارند.
* replay نمای **فعلی** منبع اصلی را با `Idempotent-Replayed: true` برمی‌گرداند.
* نگهداری: ۲۴ ساعت (`waltrix purge-idempotency`). کلید منقضی‌شده دوباره قابل استفاده است.
* API روی هر مسیری که پول جابه‌جا می‌کند `Idempotency-Key` را **اجباری** می‌داند.

Waltrix ادعای «تحویل دقیقاً یک‌باره» ندارد: شبکه همیشه می‌تواند پاسخ را گم کند. تضمینش این است که درخواست
تکراری با همان کلید **حداکثر یک بار اعمال می‌شود** و کلاینت همیشه می‌تواند با تلاش دوباره نتیجه را بفهمد.

## رفتار retry کلاینت (هر دو SDK)

* فقط GETها و POSTهای دارای کلید idempotency تکرار می‌شوند (متدهای جابه‌جایی پول همیشه کلید دارند؛ یک بار
  برای هر فراخوانی ساخته و در همه‌ی تلاش‌ها استفاده می‌شود).
* تکرار برای timeout، خطای اتصال، 429، 502/503/504 و `409 concurrent_request`، با backoff نمایی و jitter
  کامل، با رعایت `Retry-After`.
* اگر یک mutation هرگز پاسخ قطعی نگیرد، `UnknownOutcomeError` / `WaltrixUnknownOutcomeError` همراه با کلید
  پرتاب می‌شود. داشبورد «نتیجه نامعلوم» را نشان می‌دهد و با ارسال دوباره با همان کلید بررسی می‌کند؛ هرگز قبل
  از تأیید سرور موفقیت نشان نمی‌دهد. تا وقتی نتیجه نامعلوم است، تغییر زبان داشبورد هم قفل است.

## بازیابی و محدودیت‌هایش

* **crash API:** تراکنش‌های در جریان rollback می‌شوند؛ کلاینت‌ها با کلیدشان دوباره تلاش می‌کنند.
* **crash worker:** حداکثر یک رزرو وسط انقضاست؛ ACTIVE می‌ماند و دور بعد پردازش می‌شود.
* **failover دیتابیس:** تراکنش‌های commit‌شده بسته به تنظیم replication باقی می‌مانند. با replication
  ناهمگام، چند تراکنش آخر ممکن است در failover گم شوند (RPO > 0)؛ کلاینت‌هایی که با کلیدشان تلاش دوباره
  می‌کنند آن‌ها را دوباره اعمال می‌کنند. اگر RPO باید صفر باشد، از replication همگام استفاده کنید.
* **بازیابی از backup:** [استقرار](deployment.md#backup-و-بازیابی) را ببینید. بعد از restore، قبل از باز کردن
  ترافیک reconciliation را اجرا کنید.
