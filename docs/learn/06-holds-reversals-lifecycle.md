# فصل ۶ — هولد، برگشت و چرخه‌ی وضعیت

فایل‌های این فصل: `state_machine.py`، `services/operations.py` (`create_hold`، `_resolve_hold`، `expire_holds`، `reverse_transaction`)، [transaction-lifecycle.md](../financial-model/transaction-lifecycle.md)، [ADR 0005](../architecture/decisions/0005-holds-as-pending-entries.md)

## ۱. هولد یعنی چه

وقتی با کارت در هتل پرداخت می‌کنید، مبلغ «مسدود» می‌شود ولی هنوز کم نشده. بعداً یا مبلغ واقعی (شاید کمتر) **capture** می‌شود، یا مسدودی **آزاد** می‌شود، یا خودش **منقضی** می‌شود.

## ۲. هولد به‌شکل سند pending

```
create_hold ۴۰۰:   Dr wallet:a 400 (pending)   |   Cr wallet:m 400 (pending)
```

این یک سند متوازن واقعی است با `phase = "pending"`. روی ستون‌های `pending_*` اثر دارد، نه `posted_*`. پس:

```
موجودی ثبت‌شده: 1000     قابل برداشت: 1000 − 400 = 600
```

capture با مبلغ ۲۵۰:

1. اثر pending سند هولد **آزاد** می‌شود (`release_pending`: ستون‌های pending برمی‌گردند).
2. یک سند **جدید** posted برای ۲۵۰ ثبت می‌شود.
3. باقی (۱۵۰) خودبه‌خود آزاد است، چون اثر pending کل هولد برداشته شد.

نکته‌ی ظریف: سند pending خودش **هرگز تغییر نمی‌کند** (append-only). اینکه «هنوز حساب می‌شود یا نه» از وضعیت هولد مشتق می‌شود. reconciliation چک می‌کند که ستون‌های pending هر حساب دقیقاً برابر مجموع سندهای pending هولدهای ACTIVE باشد (`pending_balance_mismatch`).

## ۳. state machine صریح

```python
TRANSACTION_TRANSITIONS = {
    CREATED:  {PENDING, POSTED, FAILED},
    PENDING:  {POSTED, FAILED},
    POSTED:   {REVERSED},
    FAILED:   set(),
    REVERSED: set(),
}
```

هر تغییر وضعیت از `check_transaction_transition` عبور می‌کند. حرکت غیرمجاز (مثلاً POSTED → PENDING) خطای `invalid_state_transition` می‌دهد به‌جای اینکه بی‌صدا داده را خراب کند. تست `test_transaction_transitions_exhaustive` **همه‌ی ۲۵ جفت** (۵×۵) را امتحان می‌کند.

صورت مسئله گفته بود «همه چیز را در یک state machine نچپانید». برای همین هولد ماشین خودش را دارد (`ACTIVE → CAPTURED | RELEASED | EXPIRED`) و کیف پول هم ماشین خودش (`active ⇄ suspended → closed`).

### نگاشت هولد به تراکنش

| رویداد | هولد | تراکنش نوع hold |
| --- | --- | --- |
| ایجاد | ACTIVE | PENDING |
| capture | CAPTURED | POSTED (`posted_amount` = مبلغ capture) |
| release | RELEASED | FAILED (`failure_code=hold_released`) |
| انقضا | EXPIRED | FAILED (`failure_code=hold_expired`) |

reconciliation این نگاشت را هم چک می‌کند (`hold_state_mismatch`).

## ۴. انقضا با چند worker

```python
select(Hold).where(Hold.status == ACTIVE, Hold.expires_at <= as_of)
    .limit(1).with_for_update(skip_locked=True)
```

`SKIP LOCKED` یعنی «ردیف‌هایی را که کس دیگری قفل کرده رد کن». پس چند worker هم‌زمان هرگز یک هولد را دو بار پردازش نمی‌کنند و منتظر هم هم نمی‌مانند. هر هولد در تراکنش جدای خودش منقضی می‌شود؛ اگر worker بمیرد، حداکثر یک هولد نیمه‌کاره است که rollback شده و دفعه‌ی بعد پردازش می‌شود. تست: `test_parallel_expiry_workers_never_double_release` (۶ worker، ۳۰ هولد، مجموع دقیقاً ۳۰).

capture بعد از `expires_at` حتی اگر worker هنوز نرسیده باشد رد می‌شود (`hold_expired`). زمان واقعی مهم است، نه زمان پردازش.

## ۵. برگشت (reversal): تاریخ را پاک نکن

```
انتقال اصلی:       Dr alice 3000 | Cr bob 3000
برگشت جزئی ۱۰۰۰:  Dr bob   1000 | Cr alice 1000   (reverses_entry_id = سند اصلی)
```

- سند اصلی دست‌نخورده می‌ماند (trigger اجازه‌ی تغییر نمی‌دهد).
- یک تراکنش جدید نوع `reversal` ساخته می‌شود که به اصلی اشاره دارد.
- تراکنش اصلی `reversed_amount` را نگه می‌دارد؛ فقط وقتی کاملاً برگشت خورد به `REVERSED` می‌رود. پس «بازپرداخت جزئی» همان برگشت جزئی است.
- ردیف تراکنش اصلی `FOR UPDATE` قفل می‌شود، پس دو برگشت هم‌زمان نمی‌توانند بیش از مبلغ اصلی برگردانند. تست `test_reversal_race_cannot_double_refund`: ۱۲ برگشت ۱۰۰ تایی هم‌زمان روی انتقال ۵۰۰ ← دقیقاً ۵ موفق.

### وقتی گیرنده پول را خرج کرده

اگر Bob پول را جای دیگری فرستاده باشد، برگشت با `insufficient_funds` شکست می‌خورد. Waltrix عمداً اجازه نمی‌دهد برگشت حساب مشتری را منفی کند. این یک تصمیم کسب‌وکاری است که در سیستم واقعی ممکن است متفاوت باشد (مثلاً یک حساب «طلب از مشتری»)، ولی باید صریح باشد.

برگشت روی کیف پول **معلق** مجاز است (`check_status=False`)، چون اصلاحات باید همیشه ممکن باشند.

## تمرین‌ها

1. یک هولد بسازید، capture جزئی کنید، و در صفحه‌ی تراکنش هر دو سند (pending و posted) را ببینید. موجودی‌ها را در هر مرحله یادداشت کنید.
2. در `TRANSACTION_TRANSITIONS` اجازه‌ی `FAILED → POSTED` بدهید. کدام تست می‌شکند؟ چه سناریوی خطرناکی را این ممنوعیت جلوگیری می‌کند؟
3. «capture دوم» را طراحی کنید (چند capture جزئی از یک هولد). چه چیزی در مدل داده باید عوض شود؟
4. چرا `expire_holds` یک هولد در هر تراکنش پردازش می‌کند و نه همه را در یک تراکنش؟ مزایا و معایب را بنویسید.
