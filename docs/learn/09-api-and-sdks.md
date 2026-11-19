# فصل ۹ — طراحی API و SDK

فایل‌های این فصل: `apps/api/src/waltrix_api/{schemas,presenters,errors}.py`، `services/queries.py::paginate`، `packages/python-sdk/src/waltrix/`، `packages/typescript-sdk/src/`، [rest.md](../api/rest.md)

## ۱. شکل یکسان خطا

```json
{"error": {"code": "insufficient_funds", "message": "...", "details": {"transaction_id": "..."},
           "correlation_id": "4f2c..."}}
```

- `code` پایدار و قابل‌ماشین است؛ کلاینت روی آن تصمیم می‌گیرد، نه روی متن پیام.
- `correlation_id` در هر خطا هست؛ کاربر آن را به پشتیبانی می‌دهد و پشتیبانی در لاگ دقیقاً همان درخواست را پیدا می‌کند.
- خطاهای ۵۰۰ هرگز جزئیات داخلی (stack trace، SQL) نشان نمی‌دهند.

خطاهای دامنه (`WaltrixError`) یک `status_hint` دارند و `errors.install` آن‌ها را به HTTP ترجمه می‌کند. هسته HTTP نمی‌داند؛ فقط «پیشنهاد» می‌دهد.

## ۲. ۴۲۲ برای شکست کسب‌وکاری

`insufficient_funds` چه status‌ای باید داشته باشد؟ ۴۰۰ (درخواست غلط)؟ ۴۰۹ (تعارض)؟ ۴۰۲؟ Waltrix ۴۲۲ برمی‌گرداند و در `details.transaction_id` شناسه‌ی تراکنش FAILED ثبت‌شده را می‌دهد. مهم‌تر از عدد، **ثبات** است: جدول کدها در `rest.md` و تمایز SDK بین «شکست کسب‌وکاری» و «اعتبارسنجی» (`isBusinessFailure`).

## ۳. صفحه‌بندی cursor، نه offset

```python
stmt.where(or_(model.created_at < ts, and_(model.created_at == ts, model.id < id_)))
    .order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)
```

با `OFFSET 50`:

- اگر بین درخواست صفحه‌ی ۱ و ۲ یک تراکنش جدید بیاید، همه چیز یکی جابه‌جا می‌شود و یک ردیف **دو بار** دیده می‌شود. در دفتری که مدام رشد می‌کند این قطعی است.
- `OFFSET 100000` یعنی دیتابیس ۱۰۰ هزار ردیف را بخواند و دور بریزد.

cursor (keyset) جای آخرین ردیف را به‌شکل `(created_at, id)` نگه می‌دارد. `id` به‌عنوان tie-breaker لازم است چون دو ردیف ممکن است `created_at` یکسان داشته باشند. `limit + 1` خوانده می‌شود تا بدون `COUNT` بفهمیم صفحه‌ی بعدی هست یا نه. cursor یک base64 مات است تا کلاینت به ساختارش وابسته نشود.

## ۴. نسخه‌بندی و قرارداد

همه چیز زیر `/api/v1` است. OpenAPI خودکار در `/api/v1/openapi.json` منتشر می‌شود. یک تست (`test_openapi_documents_idempotency`) چک می‌کند که `Idempotency-Key` در schema **اجباری** مستند شده باشد. اول این‌طور نبود (فصل ۱۳): تابع چک می‌کرد ولی schema می‌گفت اختیاری است.

## ۵. SDK پایتون: یک جدول، دو کلاینت

مشکل: می‌خواهیم کلاینت sync و async با همان ۲۵ متد و همان type hintها. نوشتن دو بار یعنی دو بار باگ.

راه‌حل در `_endpoints.py` و `client.py`: هر endpoint یک تابع تایپ‌شده است که یک `Spec[T]` (توصیف درخواست) برمی‌گرداند. دو تابع کمکی با `ParamSpec` آن را به متد sync یا async تبدیل می‌کنند:

```python
def _sync(fn: Callable[P, ep.Spec[T]]) -> Callable[Concatenate[Any, P], T]:
    def method(self: Any, /, *args: P.args, **kwargs: P.kwargs) -> T: ...

class Wallets(_Resource):
    create = _sync(ep.create_wallet)

class AsyncWallets(_Resource):
    create = _async(ep.create_wallet)
```

`ParamSpec` امضای تابع اصلی را حفظ می‌کند، پس mypy برای `client.transfers.create(a, b, 1.5, "USD")` خطای «float به‌جای int» می‌دهد و `await aclient.wallets.get(...)` تایپ `Wallet` دارد. این را با `reveal_type` امتحان کردیم.

اسلش در `self: Any, /` یعنی `self` فقط positional است. بدون آن mypy می‌گفت ممکن است کسی `self=` را به‌عنوان keyword بفرستد و امضا با `Concatenate` نمی‌خواند.

## ۶. SDK تایپ‌اسکریپت

- **دو حالت احراز هویت:** `apiKey` برای سرور، `session` برای مرورگر (کوکی + هدر CSRF + سازمان). ترکیب هر دو خطاست.
- **لغو:** هر متد `AbortSignal` می‌گیرد؛ timeout داخلی با یک `AbortController` جدا ترکیب می‌شود.
- **شناسه در مسیر:** `seg()` با `encodeURIComponent` و رد `/` جلوی `../api-keys` را می‌گیرد (path traversal در کلاینت).
- **ماژول money:** `parseMoney`/`formatMoney` روی رشته و عدد صحیح کار می‌کنند. `Intl.NumberFormat` رشته‌ی اعشاری را مستقیم قبول می‌کند، پس هیچ تقسیم float لازم نیست.

## ۷. مثال‌ها اجرا شده‌اند

`examples/python-integration/checkout.py` (هولد، capture جزئی، refund) و `examples/typescript-integration/index.ts` (payout با کلید idempotency از دامنه) هر دو روی سرور واقعی اجرا شدند. مثالی که اجرا نشده، مستندات نیست؛ امید است.

## تمرین‌ها

1. متد `wallets.close` را به SDK پایتون اضافه کنید (endpoint در API هست). چند خط کد لازم شد؟ آیا sync و async هر دو کار می‌کنند؟
2. صفحه‌بندی offset را برای `/wallets` پیاده کنید و تستی بنویسید که با insert هم‌زمان بین دو صفحه، تکرار ردیف را نشان دهد. بعد همان تست را با cursor اجرا کنید.
3. در SDK تایپ‌اسکریپت، retry برای خطای ۵۰۰ روی GET وجود ندارد. آیا باید باشد؟ استدلال کنید و اگر لازم است پیاده کنید.
4. یک `.pyi` یا تست mypy بنویسید که ثابت کند `client.holds.capture("h", amount=1.5)` خطای تایپ می‌دهد.
