# فصل ۱۱ — تست

فایل‌های این فصل: `tests/fixtures.py`، `tests/unit/`، `tests/integration/`، `tests/concurrency/`، `apps/api/tests/`، `packages/python-sdk/tests/`، `apps/web/src/**/*.test.tsx`، `apps/web/e2e/`

## ۱. هرم تست این پروژه

| لایه | ابزار | تعداد (آخرین اجرا) | چه چیزی را ثابت می‌کند |
| --- | --- | --- | --- |
| دامنه‌ی خالص | pytest + Hypothesis | بخشی از ۱۵۶ | قوانین سند، پول، state machine، مجوز |
| integration | pytest + PostgreSQL واقعی | بخشی از ۱۵۶ | ۱۰ ناوردایی مالی، trigger و constraint |
| همزمانی | thread + Barrier | بخشی از ۱۵۶ | بدون خرج دوباره، بدون deadlock، بدون اجرای دوباره |
| property stateful | Hypothesis `RuleBasedStateMachine` | ۱ (۱۲ نمونه × ۲۰ گام) | رفتار دفتر = یک مدل ساده |
| HTTP | FastAPI TestClient | ۳۱ | احراز هویت، tenant، اعتبارسنجی، صفحه‌بندی |
| SDK | httpx MockTransport + سرور واقعی | ۱۸ | retry، کلید، نگاشت خطا |
| فرانت | Vitest + Testing Library | ۱۳ + ۳۰ (SDK) | state machine انتقال، صفحه‌ی انتقال |
| E2E | Playwright | ۵ | مسیرهای حیاتی کاربر، دسکتاپ و موبایل |

## ۲. چرا PostgreSQL واقعی و نه SQLite

قفل `FOR UPDATE`، `SKIP LOCKED`، trigger تأخیری، CHECK با عبارت، `ON CONFLICT`، `REPEATABLE READ`: هیچ‌کدام در SQLite به همان شکل وجود ندارند. تست ناوردایی روی دیتابیسی که این ویژگی‌ها را ندارد، فقط ثابت می‌کند تست سبز است. `scripts/dev-db.sh` بدون Docker و بدون sudo یک cluster خصوصی PostgreSQL در `.local/pgdata` بالا می‌آورد.

`tests/fixtures.py` یک بار در هر session، migrationها را downgrade و upgrade می‌کند (پس خود migration هم تست می‌شود) و قبل از هر تست `TRUNCATE` می‌زند. چرا TRUNCATE و نه rollback هر تست؟ چون تست‌های همزمانی چند اتصال دارند و باید داده‌ی commit شده‌ی همدیگر را ببینند. (TRUNCATE trigger ردیفی را فعال نمی‌کند، پس با append-only بودن تداخل ندارد.)

## ۳. تست ناوردایی‌ها، نه تابع‌ها

نام تست‌ها شماره‌ی ناوردایی دارد: `test_1_...` تا `test_10_...`. هر تست به یک سؤال جواب می‌دهد، نه به «آیا این تابع کار می‌کند». چند نمونه‌ی جالب:

- `test_3_failure_mid_operation_commits_nothing` با `monkeypatch` بعد از flush سطرهای سند exception پرتاب می‌کند (شبیه‌سازی crash)، بعد ثابت می‌کند تعداد سطرها تغییر نکرده **و** کلید idempotency هنوز آزاد است.
- `test_4_journal_is_append_only` با `parametrize` پنج دستور UPDATE/DELETE را امتحان می‌کند.
- `test_1_database_rejects_unbalanced_entry_at_commit` موتور را دور می‌زند و مستقیم با ORM سند نامتوازن می‌سازد.

## ۴. تست همزمانی

```python
def run_concurrently(factory, n, fn):
    barrier = threading.Barrier(n)
    def worker(i):
        s = factory()
        barrier.wait(timeout=30)   # همه دقیقاً با هم شروع کنند
        return fn(s, i)
```

بدون `Barrier`، thread اول احتمالاً قبل از ساخته شدن thread دهم کارش تمام شده و هیچ رقابتی رخ نمی‌دهد: تست سبز می‌شود ولی هیچ چیز را ثابت نمی‌کند. هر thread session (اتصال) خودش را دارد. exceptionها جمع می‌شوند و در پایان assert می‌شوند.

تست stress: ۱۶ thread × ۳۰ عملیات تصادفی روی ۶ کیف پول هم‌پوشان، و هر انتقال **بلافاصله با همان کلید تکرار** می‌شود (شبیه‌سازی retry بعد از timeout) و باید replay باشد. در پایان: پول حفظ شده، هیچ موجودی منفی نیست، reconciliation سبز است. این تست درستی است، نه benchmark؛ هیچ عدد کارایی ادعا نمی‌شود.

## ۵. تست property-based

```python
@given(st.lists(st.integers(1, 10**12), min_size=1, max_size=8), st.integers(1, 8))
def test_property_split_credits_balance(self, debits, n_credit): ...
```

به‌جای چند مثال دست‌ساز، Hypothesis صدها ورودی تصادفی (و ورودی‌های مرزی) می‌سازد. قوی‌تر از آن، **تست stateful** (`test_property_ledger.py`): Hypothesis دنباله‌های تصادفی از واریز، برداشت، انتقال، هولد، capture، release و برگشت می‌سازد. بعد از **هر گام**، موجودی واقعی هر کیف پول با یک مدل ساده‌ی پایتونی (یک dict) مقایسه می‌شود. اگر شکست بخورد، Hypothesis دنباله را **کوچک می‌کند** (shrinking) و کوتاه‌ترین دنباله‌ی شکست را نشان می‌دهد.

**درس:** مدل باید آن‌قدر ساده باشد که آشکارا درست باشد. کل منطق مدل چند خط جمع و تفریق است.

## ۶. تست SDK بدون شبکه

`httpx.MockTransport` اجازه می‌دهد سرور را با یک تابع پایتونی جایگزین کنید: «دو بار اول timeout بده، بار سوم ۲۰۱». تست چک می‌کند هر سه تلاش **همان** `Idempotency-Key` را فرستاده‌اند. تست round-trip هم `TestClient` خود FastAPI را به‌عنوان `http_client` به SDK می‌دهد: SDK واقعی، API واقعی، دیتابیس واقعی، بدون پورت.

## ۷. Playwright

`playwright.config.ts` قبل از تست‌ها یک دیتابیس جدا (`waltrix_e2e`) را migrate می‌کند و API را با build داشبورد روی پورت ۴۸۲۳ بالا می‌آورد. پنج مسیر: شارژ و انتقال با بازبینی تا دیدن سند متوازن، شکست قطعی اضافه‌برداشت (با دور زدن UI)، reconciliation و audit، نمایش یک‌باره‌ی راز API key، و ناوبری موبایل روی Pixel 7.

## ۸. نتایج واقعی

نتایج آخرین اجرا در README آمده (۱۵۶ پایتون در ۲۸.۶ ثانیه، ۳۰ SDK، ۱۳ داشبورد، ۵ Playwright). قاعده: هیچ عددی که اجرا نشده نوشته نمی‌شود.

## تمرین‌ها

1. در `test_concurrent_debits_cannot_overspend` خط `barrier.wait` را حذف کنید و تست را ۲۰ بار اجرا کنید. آیا همیشه سبز است؟ آیا این یعنی کد درست است؟
2. در `operations.transfer` یک باگ عمدی بگذارید: موجودی را **قبل** از قفل بخوانید. کدام تست‌ها آن را می‌گیرند؟ کدام نمی‌گیرند؟
3. `max_examples` تست stateful را به ۲۰۰ برسانید و اجرا کنید. یک قاعده‌ی جدید (مثلاً «تعلیق و فعال‌سازی کیف پول») به machine اضافه کنید.
4. یک تست Playwright برای «Result unknown» بنویسید (راهنمایی: `page.route` برای قطع پاسخ بعد از رسیدن درخواست به سرور).
