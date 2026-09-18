# ماس — مدیریت اتاق سخنرانی

نسخهٔ بازنویسی‌شدهٔ پلتفرم «ماس» با FastAPI + SQLAlchemy + Jinja2 و Frontend جداشده از Backend است.

## قابلیت‌ها

- ثبت‌نام، ورود، خروج و Session قابل ابطال با کوکی HttpOnly
- CSRF برای عملیات تغییر‌دهنده
- محدودسازی تلاش‌های ورود و ثبت‌نام بر پایهٔ IP/نام کاربری، بدون Account Lockout ساده
- تکمیل و ویرایش پروفایل
- خانه و مدیریت اتاق‌ها
- ظرفیت ۱ تا ۱۰۰ سخنران
- نام، جنسیت، سن، توضیحات و زمان سخنرانی
- زمان همگانی یا اختصاصی
- ترتیب سنی، الفبایی، تصادفی و دستی با Drag & Drop
- آپلود فایل همگانی و اختصاصی با محدودیت حجم/تعداد/سهمیه
- مشاهده و دانلود فایل
- پاک‌سازی مطمئن فایل‌های حذف‌شده با صف Cleanup
- ضبط صدا از میکروفون مرورگر و ثبت آن در آرشیو ضبط‌ها
- Playback پایدار با DOM ثابت و همگام‌سازی امن با Backend
- تایمر Backend-based، مستقل برای هر سخنران و مبتنی بر `current_speaker_id`
- Start / Pause / Reset / Next / Previous و نمایش Overtime
- صفحهٔ آرشیو فایل‌های ضبط‌شده
- Security Headers و CSP بدون inline JavaScript اجرایی
- SQLite برای شروع و PostgreSQL برای چندکاربره/Production
- مهاجرت خودکار حداقلی برای schema نسخهٔ قدیمی پروژه
- تست‌های Unit/Integration و بررسی syntax جاوااسکریپت

## اجرای محلی

Python 3.11 یا 3.12 پیشنهاد می‌شود:

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# Linux/macOS
source .venv/bin/activate
pip install -r requirements-dev.txt
```

سپس یک Secret حداقل ۳۲ کاراکتری قرار دهید و اجرا کنید:

```bash
uvicorn main:app --reload
```

و به:

`http://127.0.0.1:8000/login`

بروید.

## Production

برای استفادهٔ واقعی، PostgreSQL پیشنهاد می‌شود. فایل‌ها نیز باید روی storage پایدار یا Object Storage قرار بگیرند. مقدار `MAS_STORAGE_DIR` برای storage محلی قابل تنظیم است؛ پیش‌فرض `./uploads` است تا با نسخهٔ قبلی سازگار بماند.

اگر روی Render از filesystem موقتی استفاده می‌کنید، فایل‌های Local با restart/redeploy قابل اتکا نیستند؛ برای دوام فایل‌ها باید Persistent Disk یا Object Storage تنظیم شود. این محدودیت پلتفرم است و با کدنویسی صرف حل نمی‌شود.

## تست

این نسخه در زمان تحویل ۲۰ تست Unit/Integration دارد که مسیرهای احراز هویت، اتاق، ۱۰۰ سخنران، فایل، ضبط، تایمر، XSS، CSRF، مهاجرت و همزمانی را پوشش می‌دهند.

```bash
pytest -q
```

برای بررسی syntax فایل‌های JS:

```bash
node --check mas_app/static/play.js
node --check mas_app/static/room_editor.js
node --check mas_app/static/files.js
```

برای راهنمای جایگزینی فایل‌ها و استقرار، `REPLACE_GITHUB.md` و برای فهرست تغییرات، `CHANGELOG.md` را ببینید.

## سازگاری با استقرار قبلی

در ریشهٔ پروژه یک `main.py` سازگارکننده وجود دارد؛ بنابراین دستور قدیمی `uvicorn main:app` نیز معتبر است. مسیر پیش‌فرض فایل‌ها `./uploads` و مسیر پیش‌فرض SQLite، `./mas.db` است تا داده‌های محلی نسخهٔ قبلی راحت‌تر حفظ شوند. قبل از هر Migration/Deployment از Database و فایل‌ها نسخهٔ پشتیبان بگیرید.
