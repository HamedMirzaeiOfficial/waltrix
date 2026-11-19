# ناورداها و محل اعمال هر کدام

[English](../../financial-model/invariants.md) · **فارسی**

دفاع لایه‌لایه: موتور اول بررسی می‌کند (تا خطای دقیق بدهد)، دیتابیس همان قانون را اجبار می‌کند (تا یک باگ
نتواند داده‌ی غلط commit کند)، reconciliation بعداً آن را از نو حساب می‌کند (تا انحراف بی‌صدا پیدا شود)، و یک
تست آن را روی PostgreSQL واقعی ثابت می‌کند.

| # | ناوردا | موتور | دیتابیس | reconciliation | تست |
| --- | --- | --- | --- | --- | --- |
| 1 | هر سند در هر ارز تراز است و ≥ ۲ سطر دارد | `rules.validate_entry` | trigger قید تأخیری هنگام COMMIT | `unbalanced_entry`، `short_entry`، `trial_balance` | `test_1_*`، تست‌های property |
| 2 | انتقال داخلی پول را حفظ می‌کند | فقط سند دوسطری | (از ۱ نتیجه می‌شود) | `funding_vs_wallets` | `test_2_*`، تست stress |
| 3 | commit جزئی وجود ندارد | یک تراکنش برای هر عملیات + savepoint | تراکنش اتمی | `posted_without_entry`، `failed_with_postings` | `test_3_failure_mid_operation_commits_nothing` |
| 4 | تاریخچه‌ی ثبت‌شده تغییرناپذیر است | هیچ مسیر کد برای update نیست | trigger `BEFORE UPDATE OR DELETE` خطا می‌دهد | - | `test_4_journal_is_append_only` |
| 5 | برگشت تاریخچه را حفظ می‌کند | سند قرینه‌ی جدید، `reverses_entry_id` | FK به سند اصلی | `reversal_total_mismatch` | `test_5_*` |
| 6 | هر درخواست با هر کلید حداکثر یک بار اعمال می‌شود | `idempotency.claim` | یکتایی (org، operation، key) | - | `test_6_*`، تست همزمانی |
| 7 | حساب‌های محافظت‌شده هرگز منفی نمی‌شوند (با احتساب رزرو) | بررسی بعد از قفل | `ck_accounts_no_overdraft` | `overdraft` | `test_7_*`، برداشت‌های هم‌زمان |
| 8 | دسترسی بین مستأجرها ممکن نیست | هر کوئری با `org_id` فیلتر می‌شود، 404 برای دیگران | FK ترکیبی `(id, org_id)` | - | `test_8_*`، تست‌های tenancy در API |
| 9 | ارزها هرگز قاطی نمی‌شوند | بررسی ارز | FK ترکیبی `(account, org, currency)` | بررسی‌های به تفکیک ارز | `test_9_*` |
| 10 | موجودی ذخیره‌شده با دفتر روزنامه برابر است | همان تراکنش سطرها، قفل ردیف | CHECKهای نامنفی | `posted_balance_mismatch`، `pending_balance_mismatch` | `test_10_*` |
| 11 | وضعیت رزرو و تراکنش با هم سازگار است | `_resolve_hold` | CHECK `capture_has_entry` | `hold_state_mismatch` | تست‌های رزرو و رقابت |
| 12 | مبلغ‌ها عدد صحیح مثبت و ≤ 2^53−1 هستند | `validate_amount`، `StrictInt` در Pydantic | CHECK `amount > 0`، BIGINT | - | تست‌های واحد و اعتبارسنجی API |

## چرا چهار لایه و نه یکی

هر لایه یک شکل متفاوت از شکست را پوشش می‌دهد:

| لایه | چه چیزی را می‌گیرد | چه چیزی را نمی‌گیرد |
| --- | --- | --- |
| موتور | اشتباه کاربر، با کد خطای دقیق و قابل ترجمه | باگ در خود موتور |
| دیتابیس | باگ در موتور، یا کدی که موتور را دور بزند | داده‌ای که superuser تغییر داده، trigger غیرفعال، restore خراب |
| reconciliation | هر چیزی که به دیسک رسیده، با هر علتی | مشکل در داده‌ای که از نو نمی‌سازد (مثل metadata حسابرسی) |
| تست | بازگشت باگ قبل از انتشار | هر چیزی که کسی برایش تست ننوشته |

قانونی که فقط در یک لایه اعمال شود، قانونی است که یک باگ می‌تواند بشکندش.

## بررسی دستی یک ناوردا

reconciliation این‌ها را مرتب اجرا می‌کند، ولی وسط یک حادثه بهتر است مستقیم از دیتابیس بپرسید. آن‌ها را روی
یک replica فقط‌خواندنی یا داخل `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY` اجرا کنید.

**۱. هر سند در هر ارز تراز است**

```sql
SELECT p.entry_id, p.currency,
       sum(p.amount) FILTER (WHERE p.direction = 'debit')  AS debits,
       sum(p.amount) FILTER (WHERE p.direction = 'credit') AS credits
  FROM postings p
 WHERE p.org_id = :org
 GROUP BY p.entry_id, p.currency
HAVING sum(p.amount) FILTER (WHERE p.direction = 'debit')
    <> sum(p.amount) FILTER (WHERE p.direction = 'credit');
-- انتظار: هیچ ردیفی
```

**۲. پول حفظ شده است** (دارایی تأمین = بدهی کیف پول‌ها، به تفکیک ارز)

```sql
SELECT a.currency,
       sum(CASE WHEN a.code = 'system:simulated_funding' THEN a.posted_debits - a.posted_credits END) AS funding,
       sum(CASE WHEN w.id IS NOT NULL THEN a.posted_credits - a.posted_debits END)                    AS wallets
  FROM accounts a LEFT JOIN wallets w ON w.account_id = a.id
 WHERE a.org_id = :org
 GROUP BY a.currency;
-- انتظار: در هر ردیف funding = wallets (سندهای دستی بین حساب‌های داخلی جدا حساب می‌شوند)
```

**۱۰. موجودی ذخیره‌شده‌ی یک حساب با سطرهایش برابر است**

```sql
SELECT a.posted_debits, a.posted_credits,
       coalesce(sum(p.amount) FILTER (WHERE p.direction = 'debit'), 0)  AS journal_debits,
       coalesce(sum(p.amount) FILTER (WHERE p.direction = 'credit'), 0) AS journal_credits
  FROM accounts a
  LEFT JOIN postings p        ON p.account_id = a.id
  LEFT JOIN journal_entries e ON e.id = p.entry_id AND e.phase = 'posted'
 WHERE a.id = :account AND (p.id IS NULL OR e.id IS NOT NULL)
 GROUP BY a.posted_debits, a.posted_credits;
```

هر سه کوئری روی دیتابیس توسعه اجرا و بررسی شده‌اند. نسخه‌ی مرجع هر بررسی، SQL موجود در
`services/reconciliation.py` است؛ این‌ها برای خواندن ساده‌تر شده‌اند.

## اضافه کردن یک ناوردای جدید

وقتی یک قابلیت قانون تازه‌ای می‌آورد (مثلاً «سند کارمزد همیشه یک حساب درآمد را بستانکار می‌کند»):

1. **موتور:** جایی که سند ساخته می‌شود بررسی کنید و یک `BusinessRuleViolation` با کد ثابت پرتاب کنید.
2. **دیتابیس:** یک CHECK، کلید خارجی یا trigger تأخیری در یک migration **جدید** اضافه کنید. هرگز migration
   موجود را ویرایش نکنید (فصل ۱۴، داستان ۶ راهنمای یادگیری).
3. **reconciliation:** یک بررسی به `CHECKS` در `services/reconciliation.py` اضافه کنید و برچسبش را به
   `CHECK_LABELS` در `apps/web/src/features/admin.tsx` (و ترجمه‌اش را به `locales/fa.json`).
4. **تست:** یک تست شماره‌دار بنویسید که قانون را از طریق هر لایه نقض کند و گرفته شدنش را ثابت کند، از جمله
   یکی که داده را دستکاری کند و انتظار داشته باشد reconciliation شکست بخورد.
5. یک ردیف به جدول بالا اضافه کنید.

## چیزهایی که این تضمین‌ها پوشش نمی‌دهند

* superuser دیتابیس می‌تواند triggerها را غیرفعال کند یا ردیف‌ها را ویرایش کند. API را با نقشی اجرا کنید که
  مالک هیچ جدولی نیست ([امنیت](../security.md))؛ reconciliation برای پیدا کردن چیزی است که با این حال رد شده.
* تغییرناپذیری برای `journal_entries`، `postings` و `audit_events` اعمال می‌شود. `transactions` و `holds` عمداً
  رکوردهای **وضعیت** قابل تغییر هستند؛ سازگاری‌شان با دفتر روزنامه با reconciliation بررسی می‌شود.
* ناوردای ۲ فقط تا وقتی برقرار است که واریز و برداشت تنها جریان‌های بیرونی باشند. قابلیت کارمزد یا تبدیل ارز
  قانون حفظ پول خودش را لازم دارد (مثلاً «تأمین = کیف پول‌ها + درآمد»).
