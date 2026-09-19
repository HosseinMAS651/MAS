# MAS — مدیریت اتاق سخنرانی

این نسخه یک بازنویسی کامل از پروژه فعلی MAS است و برای استفاده روی FastAPI + SQLAlchemy + PostgreSQL/SQLite آماده شده است.

## قابلیت‌های اصلی

- حساب کاربری، ورود، ثبت‌نام و تکمیل پروفایل
- تغییر رمز عبور با دریافت رمز فعلی و باطل‌کردن تمام نشست‌های قبلی
- مدیریت اتاق و سخنران‌ها
- ترتیب دستی، سنی، الفبایی و تصادفی
- تایمر سرور-محور با نمایش روان در مرورگر
- زمان اضافه (Overtime) با ثبت زمان واقعی اضافه
- اعلان داخل سایت در پایان زمان مجاز
- در صورت پایان زمان: ادامه سخنرانی یا اتمام و فریز سخنران
- فریزشدن سخنران بدون حذف و امکان بازگشت به آن با «قبلی»
- اتمام دستی سخنرانی در صفحه پخش
- حذف سخنران در حالت پخش؛ با کاهش ظرفیت اتاق و انتخاب خودکار سخنران بعدی فعال
- حذف فایل، کنترل سهمیه و صف پاک‌سازی
- ضبط صوت مرورگر با کنترل مدت و حجم
- ذخیره محلی ضبط در صورت شکست Upload
- کنترل CSRF، Session امن، Rate Limit و Security Headers
- XSS-safe rendering و کنترل دسترسی مالک اتاق
- migration و repair برای چند شکل از دیتابیس‌های قدیمی
- نگهداری اطلاعات timer به میلی‌ثانیه برای جلوگیری از پرش بصری

## اجرای محلی

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

در ویندوز اگر چند نسخه Python نصب است، Python 3.12 را استفاده کن.

## تست

```bash
pip install -r requirements-dev.txt
PYTHONPATH=. pytest -q
```

نسخه‌ای که تحویل داده شده با مجموعه تست داخلی اجرا شده و ۲۰ تست سبز دارد. تست PostgreSQL واقعی به دلیل در دسترس نبودن سرور PostgreSQL در محیط ساخت اجرا نشده است؛ برای PostgreSQL، SQL مخصوص این موتور و مسیر migration با تست دیالکت و migration محلی بررسی شده‌اند.

## استقرار روی Render

نمونه `render.yaml` داخل پروژه موجود است و Start Command به صورت زیر تنظیم شده است:

```text
uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"
```

Environment Variableهای اصلی:

- `MAS_ENV=production`
- `MAS_SECRET_KEY=<حداقل 32 کاراکتر>`
- `MAS_COOKIE_SECURE=1`
- `DATABASE_URL=<آدرس PostgreSQL فعلی>`
- `MAS_STORAGE_DIR=<مسیر Storage در صورت استفاده از دیسک پایدار>`

**قبل از Deploy از دیتابیس فعلی Backup بگیر.** برنامه در Startup migration/repair انجام می‌دهد و برای حفظ داده‌های قبلی طراحی شده است، اما هیچ migration خودکاری را نباید بدون Backup روی دیتابیس مهم اجرا کرد.

برای فایل‌ها نیز در Render از Storage پایدار یا Object Storage استفاده کن. فایل‌های محلی یک container معمولی Render برای دوام طولانی‌مدت مناسب نیستند.

## نکته درباره داده‌های قدیمی

نسخه جدید ستون `started_at_ms` را برای تایمر استفاده می‌کند. اگر دیتابیس قدیمی ستون `started_at` را به صورت TIMESTAMP ساخته باشد، نسخه جدید آن مقدار قدیمی را می‌خواند ولی دیگر آن ستون legacy را هنگام اجرای تایمر overwrite نمی‌کند.

در Startup مواردی مانند order سخنران‌ها، stateهای تکراری تایمر/اتاق و بعضی رکوردهای تکراری Storage repair می‌شوند و سپس Unique Indexهای لازم ساخته می‌شوند.

## ساختار

- `main.py` — entry point
- `mas_app/main.py` — routeها و application lifecycle
- `mas_app/models.py` — مدل‌های دیتابیس
- `mas_app/db.py` — Engine و migration/repair
- `mas_app/services.py` — منطق تایمر، اتاق، فایل و Storage quota
- `mas_app/auth.py` — Session، CSRF، password hashing و rate limit
- `mas_app/storage.py` — Upload/Storage/Reconciliation
- `mas_app/templates/` — رابط HTML
- `mas_app/static/` — JavaScript/CSS
- `tests/` — تست‌های regression و integration
