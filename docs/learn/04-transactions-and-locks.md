# فصل ۴ — تراکنش، قفل و همزمانی

[English](en/04-transactions-and-locks.md) · **فارسی**

فایل‌های این فصل: `services/runner.py`، `services/ledger.py::lock_accounts`، `services/operations.py`، `tests/concurrency/test_concurrency.py`، [ADR 0003](../fa/architecture/decisions/0003-locking-strategy.md)

این مهم‌ترین فصل پروژه است. سخت‌ترین باگ‌های سیستم‌های مالی از همزمانی می‌آیند: دو درخواست در یک لحظه.

## ۱. مسئله‌ی کلاسیک: خرج دوباره (double spend)

کیف پولی ۱۰۰ دلار دارد. دو درخواست برداشت ۱۰۰ دلاری هم‌زمان می‌رسند:

```
درخواست A: موجودی را می‌خواند → 100     درخواست B: موجودی را می‌خواند → 100
A: 100 >= 100 ✓ → کم می‌کند            B: 100 >= 100 ✓ → کم می‌کند
نتیجه: ۲۰۰ دلار خرج شد از ۱۰۰ دلار
```

این همان الگوی **check-then-act** است: بین «چک کردن» و «عمل کردن» فاصله هست.

## ۲. راه‌حل: قفل ردیف، بعد چک

```python
def lock_accounts(session, org_id, account_ids):
    ids = sorted(set(account_ids))
    rows = session.execute(
        select(Account)
        .where(Account.org_id == org_id, Account.id.in_(ids))
        .order_by(Account.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalars().all()
```

- `FOR UPDATE` ردیف را تا پایان تراکنش قفل می‌کند. درخواست B روی همین `SELECT` **صبر می‌کند** تا A commit یا rollback شود.
- وقتی B قفل را گرفت، در سطح ایزولاسیون READ COMMITTED مقدار **commit شده‌ی جدید** را می‌خواند (۰ دلار) و `insufficient_funds` می‌گیرد.
- `populate_existing=True` مهم است: SQLAlchemy یک identity map دارد و اگر این شیء قبلاً در session بوده، بدون این گزینه ممکن است مقدار **قدیمی** حافظه را به شما بدهد، حتی بعد از گرفتن قفل!

تست `test_concurrent_debits_cannot_overspend`: کیف پول ۱۰۰۰ دلاری، ۴۰ برداشت ۱۰۰ دلاری **دقیقاً هم‌زمان** (با `threading.Barrier`). نتیجه همیشه: ۱۰ موفق، ۳۰ ناموفق، موجودی صفر.

## ۳. بن‌بست (deadlock) و ترتیب قفل

انتقال A→B قفل A بعد B را می‌گیرد. هم‌زمان انتقال B→A قفل B بعد A را. هر کدام منتظر دیگری: **deadlock**. PostgreSQL یکی را می‌کشد، ولی ما یک خطای تصادفی به کاربر داده‌ایم.

راه‌حل: `sorted(set(account_ids))`. هر دو تراکنش اول `min(A, B)` را قفل می‌کنند؛ یکی منتظر می‌ماند، هیچ چرخه‌ای ساخته نمی‌شود. تست `test_opposite_transfers_do_not_deadlock` چهل انتقال در دو جهت را هم‌زمان اجرا می‌کند.

### ترتیب سراسری بین عملیات‌های مختلف

مرتب کردن حساب‌ها کافی نیست؛ عملیات‌های مختلف ردیف‌های **دیگری** را هم قفل می‌کنند (کیف پول، هولد، تراکنش اصلی برای reversal). پس یک ترتیب سراسری تعریف شده (بالای `operations.py`):

```
کلید idempotency  →  ردیف تراکنش / هولد  →  کیف پول‌ها (به ترتیب id)  →  حساب‌ها (به ترتیب id)
```

در حین نوشتن همین پروژه، `_resolve_hold` ردیف تراکنش را **بعد** از حساب‌ها قفل می‌کرد، در حالی که reversal آن را **قبل** از حساب‌ها قفل می‌کند: یک deadlock بالقوه. اصلاح شد تا ترتیب یکسان باشد. (فصل ۱۳)

## ۴. FOR SHARE برای کیف پول

کیف پول‌ها با `with_for_update(read=True)` یعنی `FOR SHARE` قفل می‌شوند:

- دو انتقال هم‌زمان روی یک کیف پول همدیگر را روی ردیف کیف پول **نمی‌بندند** (قفل اشتراکی با قفل اشتراکی سازگار است). آن‌ها روی ردیف حساب منتظر می‌مانند.
- ولی `set_wallet_status` (تعلیق) با `FOR UPDATE` قفل می‌گیرد و منتظر می‌ماند تا انتقال‌های در جریان تمام شوند. پس کیف پول نمی‌تواند «وسط» یک انتقال معلق شود.

## ۵. چرا SERIALIZABLE نه؟

ایزولاسیون SERIALIZABLE همین ایمنی را بدون قفل صریح می‌دهد، ولی به‌جای «صبر کردن»، تراکنش‌های متضاد را با `serialization_failure` **رد** می‌کند. روی یک کیف پول پرترافیک یعنی سیل خطا که همه‌ی کلاینت‌ها باید درست retry کنند. با قفل صریح، رفتار عادی زیر فشار «صبر» است، نه «شکست». هزینه‌اش انضباط در ترتیب قفل است.

## ۶. مرز تراکنش: `run_operation`

```python
with session.begin():
    session.execute(text("SET LOCAL lock_timeout = '5000ms'"))
    record, stored = idempotency.claim(...)          # فصل ۵
    try:
        with session.begin_nested():                 # SAVEPOINT
            rtype, rid = execute(session)
    except BusinessRuleViolation as err:
        failed = on_failure(session, err)            # ثبت تراکنش FAILED
    idempotency.complete(record, ...)
# COMMIT: trigger‌های تأخیری اینجا اجرا می‌شوند
```

- **یک COMMIT** یعنی نوشتن جزئی غیرممکن است. اگر پروسه وسط کار بمیرد، PostgreSQL با قطع اتصال همه چیز را rollback می‌کند. تست `test_3_failure_mid_operation_commits_nothing` بعد از flush شدن سطرهای سند یک exception پرتاب می‌کند و نشان می‌دهد هیچ چیز ثبت نشده.
- **SAVEPOINT**: اگر قانون کسب‌وکاری (مثل موجودی ناکافی) نقض شود، فقط تغییرات داخل savepoint برمی‌گردد و ما هنوز می‌توانیم در همان تراکنش یک «تراکنش FAILED» ثبت کنیم.
- **`lock_timeout`**: اگر قفلی بیش از ۵ ثانیه طول بکشد، به‌جای صبر بی‌پایان خطای `55P03` می‌آید و به `409 concurrent_request` (قابل retry) تبدیل می‌شود.

## ۷. حساب داغ (hot account)

همه‌ی واریزها حساب `system:simulated_funding` را قفل می‌کنند؛ پس واریزهای یک ارز پشت‌سرهم اجرا می‌شوند. برای پروژه‌ی آموزشی قابل قبول است و در ADR ثبت شده. راه‌حل‌های واقعی: شکستن حساب به چند shard، یا بافر کردن ثبت‌ها.

## تمرین‌ها

1. در `lock_accounts` خط `sorted` را بردارید (`ids = list(set(account_ids))`) و `test_opposite_transfers_do_not_deadlock` را چند بار اجرا کنید. خطا چیست و چرا «گاهی» رخ می‌دهد؟
2. `populate_existing=True` را بردارید. آیا تستی می‌شکند؟ اگر نه، تستی بنویسید که این باگ را نشان دهد (راهنمایی: شیء حساب را قبل از قفل در همان session بارگذاری کنید).
3. `lock_timeout` را به `'1ms'` تغییر دهید و تست stress را اجرا کنید. خطاهای `ConcurrentRequest` چطور شمرده می‌شوند و آیا ناوردایی‌ها هنوز برقرارند؟
4. با دو پنجره‌ی `psql` یک deadlock دستی بسازید (`BEGIN; SELECT ... FOR UPDATE` به ترتیب متفاوت) و پیام PostgreSQL را ببینید.
