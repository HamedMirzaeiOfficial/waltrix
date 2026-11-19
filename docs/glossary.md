# Glossary · واژه‌نامه

One table for both languages. The **dashboard label** column is exactly what the Persian dashboard shows
(from `apps/web/src/locales/fa.json`), so docs, code and UI use the same words.

یک جدول برای هر دو زبان. ستون **برچسب داشبورد** دقیقاً همان چیزی است که داشبورد فارسی نشان می‌دهد
(از `apps/web/src/locales/fa.json`)، تا مستندات، کد و رابط کاربری یک زبان مشترک داشته باشند.

## Accounting · حسابداری

| English | فارسی (docs) | Dashboard label | Meaning | معنی |
| --- | --- | --- | --- | --- |
| Ledger | دفتر کل | دفتر کل | All accounts of one organization | همه‌ی حساب‌های یک سازمان |
| Journal | دفتر روزنامه | دفتر روزنامه | The append-only list of journal entries | فهرست فقط‌افزودنی سندها |
| Journal entry | سند | سند | One financial event; balanced and immutable | یک رویداد مالی؛ تراز و تغییرناپذیر |
| Posting | سطر سند | سطر سند | One debit or credit line on one account | یک سطر بدهکار یا بستانکار روی یک حساب |
| Debit / Credit | بدهکار / بستانکار | بدهکار / بستانکار | The two sides of every entry | دو طرف هر سند |
| Normal balance | ماهیت حساب | ماهیت حساب | The side that increases an account | طرفی که مانده‌ی حساب را زیاد می‌کند |
| Asset / Liability / Equity / Revenue / Expense | دارایی / بدهی / سرمایه / درآمد / هزینه | same | Account types | نوع حساب |
| Chart of accounts | فهرست حساب‌ها | فهرست حساب‌ها | Every account and its type | همه‌ی حساب‌ها با نوعشان |
| Trial balance | تراز آزمایشی | تراز آزمایشی | Total debits equal total credits, per currency | جمع بدهکار برابر جمع بستانکار، به تفکیک ارز |
| Minor unit | واحد خرد | — | Cents for USD; every amount is an integer of these | سنت برای دلار؛ همه‌ی مبلغ‌ها عدد صحیح به این واحدند |
| Balanced / Unbalanced | تراز / ناتراز | تراز / ناتراز | Whether debits equal credits | برابر بودن بدهکار و بستانکار |

## Money movement · جابه‌جایی پول

| English | فارسی (docs) | Dashboard label | Meaning | معنی |
| --- | --- | --- | --- | --- |
| Wallet | کیف پول | کیف پول | A customer balance, backed by one liability account | موجودی یک مشتری، با پشتوانه‌ی یک حساب بدهی |
| Transfer | انتقال | انتقال | Wallet to wallet in one balanced entry | از کیف پول به کیف پول در یک سند تراز |
| Deposit / Withdrawal | واریز / برداشت | واریز / برداشت | Simulated funding in and out | ورود و خروج از منبع تأمین شبیه‌سازی‌شده |
| Hold | رزرو (هولد) | رزرو | Funds set aside but not moved yet | وجهی که کنار گذاشته شده ولی هنوز منتقل نشده |
| Capture | نهایی‌سازی (capture) | نهایی‌سازی | Turns a hold into a posted movement | تبدیل رزرو به جابه‌جایی ثبت‌شده |
| Release | آزادسازی | آزادسازی | Returns held funds to available | برگرداندن وجه رزروشده به موجودی قابل استفاده |
| Reversal | برگشت | برگشت | An opposite entry that corrects; the original stays | سند معکوس برای اصلاح؛ سند اصلی می‌ماند |
| Posted / Pending | ثبت‌شده / در انتظار | ثبت‌شده / در انتظار | Final vs. reserved entries | سند نهایی در برابر سند رزرو |
| Available balance | موجودی قابل استفاده | قابل استفاده | Posted minus outgoing holds | ثبت‌شده منهای رزروهای خروجی |
| Simulated funding | تأمین شبیه‌سازی‌شده | تأمین شبیه‌سازی‌شده | Synthetic source for deposits; no real bank | منبع ساختگی واریز؛ بدون بانک واقعی |

## Reliability · قابلیت اطمینان

| English | فارسی (docs) | Dashboard label | Meaning | معنی |
| --- | --- | --- | --- | --- |
| Idempotency key | کلید idempotency | کلید idempotency | Lets a request be retried and applied only once | اجازه می‌دهد درخواست دوباره فرستاده شود و فقط یک بار اثر کند |
| Fingerprint | اثر انگشت | — | Hash of the request parameters stored with the key | hash پارامترهای درخواست که کنار کلید ذخیره می‌شود |
| Unknown outcome | نتیجه‌ی نامعلوم | نتیجه نامعلوم | No definitive answer; verify with the same key | پاسخ قطعی نیامده؛ با همان کلید بررسی کنید |
| Reconciliation | تطبیق | تطبیق | Rebuild balances from the journal and compare | بازسازی موجودی‌ها از دفتر روزنامه و مقایسه |
| Invariant | ناوردا | ناوردای دفتر کل | A rule that must always hold | قانونی که همیشه باید برقرار باشد |
| Lock order | ترتیب قفل | — | The fixed order in which rows are locked | ترتیب ثابت قفل کردن ردیف‌ها |
| Deadlock | بن‌بست (deadlock) | — | Two transactions waiting for each other | دو تراکنش که منتظر هم مانده‌اند |
| Audit log | گزارش حسابرسی | گزارش حسابرسی | Who did what and when; separate from postings | چه کسی چه کرد و کی؛ جدا از ثبت‌های مالی |
| Correlation id | شناسه‌ی درخواست | شناسهٔ درخواست | Ties logs, audit events and entries to one request | لاگ، رویداد حسابرسی و سند را به یک درخواست وصل می‌کند |

## Access · دسترسی

| English | فارسی (docs) | Dashboard label | Meaning | معنی |
| --- | --- | --- | --- | --- |
| Organization / Tenant | سازمان / مستأجر | سازمان | A fully isolated customer of Waltrix | یک مشتری Waltrix با داده‌ی کاملاً جدا |
| Owner / Admin / Finance operator / Auditor / Viewer | مالک / مدیر / اپراتور مالی / حسابرس / بیننده | same | Roles, from most to least access | نقش‌ها، از بیشترین تا کمترین دسترسی |
| API key | کلید API | کلید API | Server-to-server credential; only its hash is stored | اعتبارنامه‌ی سرور به سرور؛ فقط hash آن ذخیره می‌شود |
| Rotation | چرخش کلید | چرخش | Issue a new secret and revoke the old one | صدور کلید تازه و باطل کردن قبلی |
