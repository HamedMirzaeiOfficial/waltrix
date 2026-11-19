# فصل ۷ — تطبیق و حسابرسی

[English](en/07-reconciliation-and-audit.md) · **فارسی**

فایل‌های این فصل: `services/reconciliation.py`، `services/audit.py`، `features/admin.tsx` (صفحه‌ی Reconciliation)، [reconciliation.md](../fa/reconciliation.md)

## ۱. «اعتماد کن، ولی چک کن»

فصل ۳ گفت trigger تأخیری اجازه نمی‌دهد سند نامتوازن commit شود. پس چرا reconciliation باز هم سندهای نامتوازن را جستجو می‌کند؟

چون تضمین‌ها **فرض‌هایی** دارند: trigger فعال است، کسی با superuser داده را دستکاری نکرده، migration درست اجرا شده، backup درست restore شده. reconciliation همه‌ی این فرض‌ها را دوباره و مستقل امتحان می‌کند. اگر روزی چیزی پیدا کند، یعنی یکی از فرض‌ها شکسته و شما آن را **قبل از مشتری** فهمیده‌اید.

## ۲. ایده: از دفتر روزنامه بازسازی کن

journal (سندها و سطرها) منبع حقیقت است. هر چیز دیگری (ستون‌های موجودی، وضعیت تراکنش و هولد) «کش» یا خلاصه است. reconciliation کش را از journal دوباره حساب می‌کند و مقایسه می‌کند:

```sql
WITH derived AS (
  SELECT p.account_id,
         sum(CASE WHEN p.direction='debit'  THEN p.amount ELSE 0 END) AS debits,
         sum(CASE WHEN p.direction='credit' THEN p.amount ELSE 0 END) AS credits
    FROM postings p JOIN journal_entries e ON e.id = p.entry_id
   WHERE p.org_id = :org AND e.phase = 'posted'
   GROUP BY p.account_id)
SELECT a.id, ... FROM accounts a LEFT JOIN derived d ON d.account_id = a.id
 WHERE a.posted_debits <> coalesce(d.debits, 0) OR ...
```

به `LEFT JOIN` و `coalesce` دقت کنید: حسابی که هیچ سطری ندارد باید موجودی صفر داشته باشد؛ اگر کش‌اش غیرصفر است، باز هم خطاست.

## ۳. ۱۲ بررسی

| بررسی | سؤالی که می‌پرسد |
| --- | --- |
| `unbalanced_entry`، `short_entry`، `trial_balance` | آیا قانون دوطرفه همه‌جا برقرار است؟ |
| `posted_balance_mismatch`، `pending_balance_mismatch` | آیا کش موجودی با journal یکی است؟ |
| `overdraft` | آیا حساب محافظت‌شده‌ای منفی شده؟ |
| `posted_without_entry`، `failed_with_postings` | آیا وضعیت تراکنش با journal می‌خواند؟ |
| `reversal_total_mismatch` | آیا `reversed_amount` با برگشت‌های واقعی برابر است؟ |
| `hold_state_mismatch` | آیا وضعیت هولد و تراکنشش با هم سازگارند؟ |
| `funding_vs_wallets` | آیا پول از هیچ ساخته شده؟ |
| `overdue_hold` (هشدار) | آیا worker انقضا عقب افتاده؟ |

## ۴. یک snapshot برای همه‌ی بررسی‌ها

```python
with session.begin():
    session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    findings, summary = run_checks(session, actor.org_id)
```

اگر ۱۲ کوئری را در READ COMMITTED بزنیم، هر کوئری snapshot **خودش** را می‌بیند. ممکن است بین کوئری ۳ و ۴ یک انتقال commit شود و بررسی‌ها با هم ناسازگار شوند: یک «خطای کاذب». در REPEATABLE READ همه‌ی کوئری‌های تراکنش همان عکس لحظه‌ی اول را می‌بینند، حتی وقتی پول در حال جابه‌جایی است. `READ ONLY` هم تضمین می‌کند reconciliation اشتباهاً چیزی ننویسد.

نتیجه در تراکنش **جداگانه‌ای** ذخیره می‌شود (`reconciliation_runs`)، چون تراکنش اول فقط‌خواندنی بود.

## ۵. تست کردن تشخیص‌دهنده

یک ابزار تشخیص که هرگز چیزی پیدا نمی‌کند، شاید فقط خراب است. تست `test_10_reconciliation_detects_tampered_cache` عمداً کش را دستکاری می‌کند:

```python
session.execute(text("UPDATE accounts SET posted_credits = posted_credits + 5 WHERE id = :id"), ...)
run = reconciliation.run_reconciliation(session, owner)
assert {"posted_balance_mismatch", "funding_vs_wallets"} <= {f["check"] for f in run.findings}
```

پنج سنت دستکاری، دو بررسی مستقل را روشن می‌کند. **درس:** برای هر هشدار، تستی داشته باشید که آن را روشن کند.

## ۶. وقتی چیزی پیدا شد

هرگز موجودی را با SQL «درست» نکنید؛ این کار بررسی بعدی را می‌شکند و رد پایی هم نمی‌گذارد. پول را با سند (برگشت یا سند دستی بین حساب‌های داخلی) اصلاح کنید تا خود اصلاح هم ثبت شود.

## ۷. audit log: جدا از پول

`audit_events` به سؤال «**چه کسی** چه کاری کرد» جواب می‌دهد: ساخت کیف پول، تغییر نقش، ساخت API key، اجرای reconciliation. journal به سؤال «**پول** چطور جابه‌جا شد» جواب می‌دهد. جدا بودنشان یعنی رویدادهای غیرمالی (مثل تغییر نقش) دفتر را شلوغ نمی‌کنند و audit log می‌تواند سیاست نگهداری متفاوتی داشته باشد.

```python
_FORBIDDEN_KEYS = {"password", "secret", "token", "api_key", "authorization", "key"}
```

`audit.record` کلیدهای حساس را از metadata حذف می‌کند، حتی اگر برنامه‌نویسی اشتباهاً آن‌ها را بفرستد. هر رویداد `correlation_id` دارد؛ با آن می‌توانید از یک خط لاگ به رویداد audit و به سند journal همان درخواست برسید.

## تمرین‌ها

1. در `psql` ستون `pending_debits` یک کیف پول را دستکاری کنید و reconciliation را از داشبورد اجرا کنید. کدام بررسی‌ها قرمز می‌شوند؟ (روی دیتابیس dev، بعد با یک reconcile و اصلاح برگردانید.)
2. سطح ایزولاسیون را به READ COMMITTED تغییر دهید و هم‌زمان با تست stress، reconciliation را مدام اجرا کنید. آیا خطای کاذب می‌بینید؟
3. بررسی سیزدهم طراحی کنید: «هیچ تراکنش PENDING نباید بیش از ۳۰ روز عمر داشته باشد». SQL آن را بنویسید و تستی که آن را روشن کند.
