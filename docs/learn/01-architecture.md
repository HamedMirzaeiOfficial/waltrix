# فصل ۱ — نقشه‌ی معماری

فایل‌های این فصل: `packages/ledger-core/`، `apps/api/src/waltrix_api/main.py`، `apps/web/src/lib/api.ts`، [ADR 0001](../architecture/decisions/0001-single-ledger-core.md)

## ۱. مسئله: پروژه دو چهره دارد

صورت مسئله می‌گوید Waltrix باید هم یک **داشبورد مستقل** باشد و هم یک **موتور مالی** که اپلیکیشن‌های دیگر داخل خودشان استفاده کنند. خطر رایج این است که منطق مالی دو یا سه نسخه پیدا کند: یک نسخه در UI («موجودی کافی است؟»)، یک نسخه در API، یک نسخه در worker. روزی این نسخه‌ها با هم اختلاف پیدا می‌کنند و دفتر شما با خودش تناقض دارد.

**قاعده‌ی این پروژه:** منطق مالی دقیقاً یک جا زندگی می‌کند: `packages/ledger-core` (پکیج پایتونی `waltrix_core`).

## ۲. لایه‌ها و جهت وابستگی

```
apps/web  ─►  @waltrix/sdk  ─HTTP─►  apps/api  ─►  waltrix_core.services  ─►  PostgreSQL
                                        ▲                 ▲
                         waltrix CLI ───┘                 └── (اپلیکیشن پایتونی میزبان)
```

| لایه | مسیر | چه می‌داند | چه نمی‌داند |
| --- | --- | --- | --- |
| دامنه‌ی خالص | `money.py`، `rules.py`، `state_machine.py`، `permissions.py` | عدد صحیح، enum | SQL، HTTP |
| پایداری | `db/models.py`، `migrations/` | SQLAlchemy، PostgreSQL | HTTP |
| use case | `services/*.py` | session، تراکنش، قفل | status code، cookie |
| انتقال | `apps/api` | FastAPI، هدرها، احراز هویت | قوانین ثبت سند |
| کلاینت | SDKها، `apps/web` | قرارداد REST عمومی | دیتابیس |

وابستگی‌ها فقط **به پایین** اشاره می‌کنند. یک تست ساده برای این قاعده: در `apps/api` هیچ‌جا `posted_debits +=` پیدا نمی‌کنید. API فقط خطاهای دامنه را به HTTP ترجمه می‌کند (`errors.py`).

**درس:** «لایه» یعنی جهت وابستگی، نه پوشه. اگر هسته `import fastapi` داشته باشد، دیگر نمی‌شود آن را در یک worker یا CLI بدون وب‌سرور استفاده کرد.

## ۳. داشبورد هیچ endpoint خصوصی ندارد

`apps/web/src/lib/api.ts`:

```ts
export const api = new Waltrix({
  baseUrl: import.meta.env.BASE_URL.replace(/\/$/, ""),
  session: { organizationId: () => organizationId },
});
```

داشبورد همان SDK تایپ‌اسکریپتی را استفاده می‌کند که یک مشتری بیرونی استفاده می‌کند، فقط در حالت session (کوکی) به‌جای API key. نتیجه:

- هر قابلیتی که داشبورد دارد، API عمومی هم دارد (dogfooding).
- هر باگی در SDK زودتر در داشبورد دیده می‌شود.
- تست‌های Playwright عملاً تست قرارداد عمومی API هم هستند.

## ۴. چرا میکروسرویس نه؟

قوی‌ترین تضمین‌های یک دفتر مالی (نوشتن اتمیک چند ردیف، قفل ردیف، constraint) از **یک تراکنش دیتابیس** می‌آیند. اگر «کیف پول» و «دفتر» دو سرویس جدا با دو دیتابیس باشند، این تضمین از بین می‌رود و جایش باید saga و جبران (compensation) بنویسید: پیچیده‌تر، کندتر، با حالت‌های میانی بیشتر.

Waltrix یک پروسه‌ی API است به‌علاوه‌ی دستورات نگهداری idempotent (`waltrix expire-holds`، `reconcile`). Redis و Celery هم عمداً نیست؛ چیزی نیست که واقعاً به آن‌ها نیاز داشته باشد. صورت مسئله هم گفته بود «فقط وقتی واقعاً لازم است».

**درس:** معماری را از تضمین‌هایی که لازم دارید شروع کنید، نه از فهرست تکنولوژی‌ها.

## ۵. هسته‌ی مستقل در عمل

یک اپلیکیشن پایتونی میزبان می‌تواند مستقیم بنویسد:

```python
from waltrix_core.migrate import upgrade
from waltrix_core.services import operations

upgrade(DATABASE_URL)  # migrationها داخل پکیج‌اند
result = operations.transfer(session, actor, source_wallet_id=a, destination_wallet_id=b,
                             amount=1250, currency="USD", idempotency_key="order-81")
```

و همان تضمین‌های API را می‌گیرد، چون همان تابع اجرا می‌شود. `Actor` (در `services/context.py`) صریحاً پاس داده می‌شود: هسته به «درخواست جاری» وب‌فریم‌ورک دسترسی ندارد، پس هویت باید شیء صریح باشد.

## ۶. ساختار مخزن

```
apps/api                  FastAPI + CLI + تست HTTP
apps/web                  داشبورد React + Vitest + Playwright
packages/ledger-core      دامنه + سرویس + migration
packages/python-sdk       کلاینت پایتون (sync و async)
packages/typescript-sdk   کلاینت تایپ‌اسکریپت
examples/                 دو یکپارچه‌سازی قابل اجرا
tests/                    تست واحد، property، integration، همزمانی (PostgreSQL واقعی)
```

## تمرین‌ها

1. در `apps/api` دنبال هر محاسبه‌ای روی موجودی بگردید (`grep -rn "balance" apps/api/src`). چه چیزهایی پیدا می‌کنید و چرا هیچ‌کدام محاسبه‌ی مالی نیستند؟
2. یک اسکریپت پایتونی کوچک بنویسید که بدون API، با `waltrix_core` یک کیف پول بسازد و شارژ کند. چه چیزهایی را باید خودتان بسازید (session، `Actor`)؟
3. فرض کنید بخواهید «کارمزد انتقال» اضافه کنید. فهرست کنید کدام فایل‌ها در کدام لایه باید تغییر کنند. آیا UI هم باید بداند کارمزد چطور محاسبه می‌شود؟
