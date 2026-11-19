# فصل ۳ — موتور ثبت و قیدهای دیتابیس

فایل‌های این فصل: `services/ledger.py`، `db/models.py`، `migrations/versions/0001_initial_schema.py`، `tests/integration/test_ledger_invariants.py`

## ۱. دفاع لایه‌لایه

برای هر قانون مالی در Waltrix چهار لایه هست:

1. **موتور** اول چک می‌کند تا پیام خطای دقیق بدهد (`insufficient_funds`).
2. **دیتابیس** همان قانون را با constraint یا trigger اجبار می‌کند تا یک باگ نتواند داده‌ی غلط commit کند.
3. **reconciliation** بعداً همه چیز را از نو حساب می‌کند تا انحراف بی‌صدا پیدا شود.
4. **تست** روی PostgreSQL واقعی ثابت می‌کند که لایه‌های بالا واقعاً کار می‌کنند.

**درس:** چک در کد برای تجربه‌ی کاربری خوب است؛ قید دیتابیس برای درستی است. هر دو لازم‌اند.

## ۲. `post_entry`: تنها جایی که پول جابه‌جا می‌شود

```python
def post_entry(session, actor, *, locked, phase, kind, description, lines, ...):
    validate_entry(lines)                       # قوانین خالص فصل ۲
    for line in lines:
        account = locked.get(line.account_id)   # حساب باید قبلاً قفل شده باشد
        if account is None: raise LedgerInvariantViolation(...)
        ...
    for line in lines: _apply(locked[line.account_id], line, phase)
    for account in touched: _check_overdraft(account)
    session.add(JournalEntry(...)); session.add(Posting(...)) ...
```

سه نکته:

- `locked` یک dict از حساب‌هایی است که **فراخواننده قبلاً قفل کرده**. موتور قبول نمی‌کند روی حسابی که قفل نشده بنویسد. این یعنی فراموش کردن قفل یک خطای برنامه‌نویسی واضح است، نه یک race condition پنهان.
- اول همه‌ی تغییرات اعمال می‌شود و بعد overdraft چک می‌شود؛ پس سندی که یک حساب را دو بار لمس کند هم درست چک می‌شود.
- `LedgerInvariantViolation` خطای «کاربر» نیست؛ یعنی باگ. API آن را به ۵۰۰ عمومی تبدیل می‌کند و جزئیاتش فقط در لاگ است.

## ۳. قیدها در `models.py`

### جلوگیری از اضافه‌برداشت در خود دیتابیس

```python
CheckConstraint(
    "allow_negative "
    "OR (normal_balance = 'credit' AND posted_credits - posted_debits - pending_debits >= 0) "
    "OR (normal_balance = 'debit'  AND posted_debits - posted_credits - pending_credits >= 0)",
    name="no_overdraft",
)
```

تست `test_7_database_check_blocks_overdraft_even_if_engine_is_bypassed` مستقیم با SQL موجودی را دستکاری می‌کند و نشان می‌دهد PostgreSQL قبول نمی‌کند.

### کلید خارجی ترکیبی: مستأجر و ارز در خود schema

```python
ForeignKeyConstraint(
    ["account_id", "org_id", "currency"],
    ["accounts.id", "accounts.org_id", "accounts.currency"],
)
```

یک FK معمولی (`account_id → accounts.id`) فقط می‌گوید «این حساب وجود دارد». FK ترکیبی می‌گوید «این حساب وجود دارد **و** مال همین سازمان است **و** ارزش همین است». برای این کار `accounts` یک `UniqueConstraint("id", "org_id", "currency")` دارد (FK باید به یک کلید یکتا اشاره کند). نتیجه: حتی SQL خام هم نمی‌تواند سطر سند سازمان A را روی حساب سازمان B بنویسد (`test_8_schema_rejects_cross_tenant_posting`) یا سطر EUR روی حساب USD (`test_9_schema_rejects_posting_in_wrong_currency`).

## ۴. تغییرناپذیری با trigger

در migration `0001`:

```sql
CREATE TRIGGER postings_append_only
  BEFORE UPDATE OR DELETE ON postings
  FOR EACH ROW EXECUTE FUNCTION waltrix_reject_mutation();
```

`UPDATE postings SET amount = amount + 1` خطا می‌دهد: «postings is append-only». اصلاح فقط با سند معکوس (فصل ۶) ممکن است. همین برای `journal_entries` و `audit_events`.

محدودیت صادقانه: superuser دیتابیس می‌تواند trigger را غیرفعال کند. برای همین در [security.md](../security.md) توصیه شده API با نقشی اجرا شود که مالک جدول‌ها نیست.

## ۵. trigger تأخیری: سند نامتوازن هرگز commit نمی‌شود

مشکل: یک سند دو سطر دارد و این دو سطر با دو `INSERT` جدا وارد می‌شوند. بعد از `INSERT` اول، سند **موقتاً** نامتوازن است. پس نمی‌شود بعد از هر INSERT چک کرد.

راه‌حل: **constraint trigger تأخیری**:

```sql
CREATE CONSTRAINT TRIGGER postings_entry_balanced
  AFTER INSERT ON postings
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION waltrix_check_entry_from_posting();
```

`INITIALLY DEFERRED` یعنی این trigger در لحظه‌ی `COMMIT` اجرا می‌شود، وقتی همه‌ی سطرها وارد شده‌اند. اگر سندی برای هر ارز متوازن نباشد یا کمتر از دو سطر داشته باشد، کل تراکنش abort می‌شود. تست `test_1_database_rejects_unbalanced_entry_at_commit` دقیقاً همین را با SQL خام امتحان می‌کند.

**درس:** بعضی قوانین روی «یک ردیف» تعریف نمی‌شوند، روی «مجموعه‌ای از ردیف‌ها در پایان تراکنش». constraint تأخیری ابزار همین کار است.

## ۶. migration منجمد است

trigger‌ها اول در یک فایل پایتون جدا بودند و migration آن را import می‌کرد. اشکال: اگر روزی آن فایل تغییر کند، migration قدیمی هم «تغییر» می‌کند و دیتابیس‌هایی که قبلاً migrate شده‌اند با دیتابیس‌های جدید فرق خواهند داشت. برای همین SQL داخل خود فایل migration کپی شد. migration باید عکسی از گذشته باشد، نه اشاره‌ای به کد حال.

## تمرین‌ها

1. در `psql` یک `UPDATE journal_entries SET description='x'` بزنید و خطا را ببینید. بعد `ALTER TABLE ... DISABLE TRIGGER` را امتحان کنید (روی دیتابیس تست!). چرا نقش runtime نباید این اجازه را داشته باشد؟
2. trigger تأخیری را موقتاً `INITIALLY IMMEDIATE` کنید و تست‌ها را اجرا کنید. چه چیزی می‌شکند و چرا؟
3. یک constraint جدید طراحی کنید: «حساب CLOSED نباید سطر جدید بگیرد». آن را با trigger بنویسید و یک تست برایش اضافه کنید.
