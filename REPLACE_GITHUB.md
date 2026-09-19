# راهنمای جایگزینی نسخه جدید MAS در GitHub و Render

این نسخه برای جایگزینی کل فایل‌های پروژه فعلی آماده شده است.

## 1) قبل از جایگزینی

اول از دیتابیس فعلی Backup بگیر.

اگر روی Render از PostgreSQL استفاده می‌کنی، مقدار فعلی `DATABASE_URL` را تغییر نده.

اگر برای فایل‌ها از Persistent Disk/Object Storage استفاده می‌کنی، مسیر و تنظیمات همان قبلی را حفظ کن.

## 2) فایل‌های GitHub

محتویات ZIP را باز کن و فایل‌ها/پوشه‌های داخل آن را در همان Repository جایگزین کن.

فایل‌های زیر جزء پروژه‌اند و باید منتقل شوند:

- `main.py`
- `mas_app/`
- `tests/`
- `requirements.txt`
- `requirements-dev.txt`
- `render.yaml`
- `.env.example`
- `.gitignore`
- مستندات موجود در ریشه پروژه

پوشه `uploads/` فقط `.gitkeep` دارد. فایل‌های واقعی Upload شده را داخل GitHub قرار نده.

همچنین فایل‌های `*.db`، `.env`، `__pycache__` و `.pytest_cache` نباید Commit شوند.

## 3) Render

Build Command:

```text
pip install -r requirements.txt
```

Start Command:

```text
uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"
```

Health Check:

```text
/health
```

Python پیشنهادی این نسخه:

```text
3.12.10
```

## 4) Environment Variables

حتماً این موارد را بررسی کن:

```text
MAS_ENV=production
MAS_COOKIE_SECURE=1
MAS_SECRET_KEY=<کلید فعلی امن>
DATABASE_URL=<همان PostgreSQL قبلی>
```

کلید `MAS_SECRET_KEY` را بی‌دلیل عوض نکن، چون عوض‌کردن آن باعث نامعتبرشدن Sessionهای قدیمی می‌شود.

## 5) بعد از Deploy

ابتدا:

```text
/health
```

را باز کن.

بعد Login با یک حساب قدیمی را تست کن.

سپس این مسیرها را بررسی کن:

1. ورود و خروج
2. پروفایل و تغییر رمز
3. اتاق و ویرایش سخنران
4. شروع/توقف/بازنشانی تایمر
5. قبلی/بعدی
6. اتمام سخنرانی و فریز
7. ادامه در زمان اضافه
8. حذف سخنران در زمان پخش
9. ضبط صوت و آرشیو ضبط‌ها
10. فایل‌های اتاق

## نکته مهم درباره دیتابیس

برنامه هنگام Startup migration/repair را اجرا می‌کند. این migration برای حفظ داده‌های قبلی طراحی شده ولی باید قبل از Deploy روی دیتابیس اصلی Backup داشته باشی.

تست PostgreSQL واقعی روی سرور Production این محیط انجام نشده است. منطق مخصوص PostgreSQL و migrationهای مهم با تست کد و compile دیالکت بررسی شده‌اند.
