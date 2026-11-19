# فصل ۱۰ — داشبورد و UX عملیات مالی

فایل‌های این فصل: `apps/web/src/features/transfer/{machine.ts,TransferPage.tsx}`، `lib/useIdempotentAction.ts`، `components/ui/data.tsx`، `index.css`، [design-system.md](../design-system.md)

## ۱. بدترین جمله در یک اپ مالی

«انتقال با موفقیت انجام شد» — وقتی هنوز نمی‌دانیم.

بیشتر UIها دو حالت دارند: موفق یا خطا. ولی در یک درخواست شبکه‌ای واقعاً **چهار** نتیجه هست:

| نتیجه | معنی | پیام Waltrix |
| --- | --- | --- |
| موفق قطعی | سرور گفت POSTED | «Transfer posted» (سبز) |
| شکست قطعی | سرور گفت مثلاً موجودی ناکافی | «Transfer failed. No money moved.» (قرمز) |
| رد شد | درخواست اجرا نشد (اعتبارسنجی، مجوز) | «Request not accepted. Nothing was executed.» (زرد) |
| **نامعلوم** | پاسخ نرسید | «Result unknown» + بررسی خودکار (زرد) |

## ۲. state machine خالص، جدا از React

`machine.ts` یک reducer خالص است، بدون React و بدون شبکه:

```
edit ──REVIEW──► review ──SUBMIT──► submitting ──► success | failed | rejected | unknown
                                         ▲                                        │
                                         └──────────────VERIFY────────────────────┘
```

قوانینی که در کد اجبار شده‌اند:

- **کلید idempotency هنگام رفتن به review ساخته می‌شود** و برای همه‌ی submit/verifyهای همان پیش‌نویس ثابت می‌ماند.
- **ویرایش، کلید را دور می‌اندازد**؛ پارامتر جدید کلید جدید می‌خواهد (وگرنه سرور ۴۰۹ می‌دهد).
- `success` **فقط** از رویداد `SUCCEEDED` (پاسخ سرور) قابل دسترسی است. هیچ مسیر خوش‌بینانه‌ای وجود ندارد.
- در حالت `submitting`، رویداد `SUBMIT` نادیده گرفته می‌شود.

چون reducer خالص است، تستش بی‌دردسر است (`machine.test.ts`): مثلاً `transferReducer(review, {type: "SUCCEEDED"})` همان `review` را برمی‌گرداند.

**درس:** منطق جریان کار را از UI جدا کنید. React برای نمایش وضعیت است، نه برای تعریف آن.

## ۳. جلوگیری از ارسال دوباره، دو لایه

1. reducer در `submitting` به `SUBMIT` بی‌اعتناست.
2. `inFlight` یک `useRef` است که در `execute` چک می‌شود:

```ts
if (inFlight.current) return; // guards double submission even across fast clicks
inFlight.current = true;
```

چرا `ref` و نه `state`؟ چون setState تا رندر بعدی اعمال نمی‌شود؛ دو کلیک در یک tick هر دو `state` قدیمی را می‌بینند. ref فوراً تغییر می‌کند. در StrictMode حالت توسعه، React افکت‌ها را دو بار اجرا می‌کند؛ همین ref جلوی درخواست دوم را هم می‌گیرد. و حتی اگر درخواست دومی برود، همان کلید را دارد و سرور replay می‌کند. سه لایه برای یک کلیک!

تست `TransferPage.test.tsx` دو `fireEvent.click` در یک tick می‌زند و چک می‌کند `create` دقیقاً یک بار صدا زده شده، حتی ۳۰۰ میلی‌ثانیه بعد از موفقیت.

## ۴. «نامعلوم» را خودکار بررسی کن

```ts
useEffect(() => {
  if (state.kind !== "unknown" || state.attempt > AUTO_VERIFY_ATTEMPTS) return;
  const t = setTimeout(() => dispatch({ type: "VERIFY" }), verifyDelayMs(state.attempt));
  return () => clearTimeout(t);
}, [state]);
```

«بررسی» یعنی ارسال دوباره‌ی **همان** درخواست با **همان** کلید. چون سرور idempotent است، این کار نتیجه‌ی اصلی را برمی‌گرداند و هرگز دو بار پول جابه‌جا نمی‌کند. سه تلاش با تأخیر ۱، ۲ و ۴ ثانیه، بعد دکمه‌ی «Check again». همچنین تا وقتی نتیجه نامعلوم است، `beforeunload` به کاربر هشدار می‌دهد صفحه را نبندد.

## ۵. صفحه‌ی بازبینی

قبل از ارسال، کاربر می‌بیند: مبلغ بزرگ، نام و `owner_reference` و شناسه‌ی کوتاه هر دو کیف پول، و «موجودی بعد از انتقال». اشتباه رایج در انتقال پول، گیرنده‌ی اشتباه با نام مشابه است؛ شناسه‌ی دوم جلوی آن را می‌گیرد.

اعتبارسنجی کلاینت (فرمت مبلغ، بیش از موجودی) فقط برای راحتی است. تست Playwright `an overspend is a confirmed failure` مستقیم با `fetch` درخواست غلط را می‌فرستد و نشان می‌دهد سرور مستقل از UI جلوی آن را می‌گیرد.

## ۶. React Query: mutation هرگز خودکار retry نمی‌شود

در `App.tsx`:

```ts
mutations: { retry: false },
queries: { retry: (count, err) => !(err instanceof WaltrixApiError && err.status < 500) && count < 1 },
```

retry برای عملیات مالی فقط در SDK و فقط با کلید انجام می‌شود. اگر React Query هم retry می‌کرد، هر تلاش یک فراخوانی جدید SDK بود با **کلید جدید**: دقیقاً همان باگی که می‌خواستیم از آن فرار کنیم.

## ۷. سیستم طراحی

- **توکن‌ها** در `index.css` به‌شکل متغیر CSS؛ Tailwind 4 با `@theme inline` آن‌ها را به کلاس‌هایی مثل `bg-surface` و `text-muted` تبدیل می‌کند. تم روشن فقط متغیرها را عوض می‌کند؛ هیچ کامپوننتی رنگ hex ندارد.
- **اعداد** با `tabular` (ارقام هم‌عرض) تا ستون‌های مبلغ تراز باشند.
- **جدول واکنش‌گرا:** `DataTable` از یک تعریف ستون، روی دسکتاپ `<table>` و روی موبایل کارت‌های پشته‌ای می‌سازد. (این باعث یک باگ جالب در تست‌های Playwright شد؛ فصل ۱۳.)
- **دسترس‌پذیری:** Radix برای focus و کیبورد، `aria-live` برای ناحیه‌ی نتیجه، ردیف‌های قابل فعال‌سازی با Enter، لینک «Skip to content»، و `prefers-reduced-motion`.

## تمرین‌ها

1. در `machine.ts` اجازه دهید `EDIT` از حالت `unknown` هم قابل انجام باشد. چرا این خطرناک است؟ سناریویی بنویسید که کاربر دو بار پول بفرستد.
2. `inFlight` را حذف کنید و StrictMode را روشن نگه دارید. در DevTools شبکه، تعداد درخواست‌ها را ببینید. چرا با این حال پول دو بار منتقل نمی‌شود؟
3. همان الگوی `useIdempotentAction` را برای دکمه‌ی «Run reconciliation» به کار ببرید. آیا لازم است؟ (راهنمایی: آیا اجرای دوباره‌ی reconciliation آسیبی دارد؟)
4. حالت «pending» واقعی طراحی کنید: اگر روزی انتقال‌ها async شوند (سرور ۲۰۲ و وضعیت PENDING بدهد)، UI باید با polling وضعیت را دنبال کند. machine را گسترش دهید.
