# جایگزینی نسخه قبلی پروژه MAS

## قبل از جایگزینی

از `mas.db` و کل پوشه `uploads/` نسخهٔ پشتیبان بگیرید. اگر Database شما PostgreSQL است، از آن backup واقعی بگیرید.

## جایگزینی در GitHub

محتویات این ZIP را در ریشهٔ Repository قرار دهید و فایل‌های نسخهٔ قبلی را با فایل‌های جدید جایگزین کنید.

دو فایل مهم را حذف نکنید:

- `main.py` در ریشه برای سازگاری با `uvicorn main:app`
- `uploads/.gitkeep` برای نگه‌داشتن پوشهٔ محلی Upload

فایل `.env` را وارد GitHub نکنید. فقط `.env.example` باید در Repository باشد.

## اجرای محلی

```bash
pip install -r requirements-dev.txt
uvicorn main:app --reload
```

سپس:

```text
http://127.0.0.1:8000/login
```

## مهاجرت دیتابیس قدیمی

در اولین startup، برنامه schema قدیمی را تشخیص می‌دهد و ستون‌های جدید لازم را به‌صورت idempotent اضافه می‌کند. داده‌های معمول کاربران، اتاق‌ها، سخنران‌ها و فایل‌ها حفظ می‌شوند.

قبل از اولین اجرا روی دیتابیس واقعی حتماً backup داشته باشید.

## Render

برای Render این مقادیر را تنظیم کنید:

- `MAS_ENV=production`
- `MAS_SECRET_KEY` حداقل ۳۲ کاراکتر و تصادفی
- `MAS_COOKIE_SECURE=1`
- `DATABASE_URL` ترجیحاً PostgreSQL
- `MAS_STORAGE_DIR` در صورت استفاده از storage محلی

Start Command:

```text
uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers
```

Health Check:

```text
/health
```

### نکتهٔ بسیار مهم Render

فایل‌های محلی و SQLite روی filesystem موقتی Render برای نگهداری دائمی مناسب نیستند. برای Database، PostgreSQL استفاده کنید؛ برای فایل‌های Upload و Recording، storage پایدار یا Object Storage لازم است. این موضوع محدودیت محیط Deploy است و صرفاً با اصلاح Python برطرف نمی‌شود.
