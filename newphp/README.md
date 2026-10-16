# MAS — بازنویسی کامل با PHP (Laravel)

این پوشه بازنویسی کامل پروژهٔ MAS است: بک‌اند Python/FastAPI به **Laravel 12 (PHP 8.3)** منتقل شده، فرانت‌اند React/TypeScript **بدون هیچ تغییری** حفظ شده و دیتابیس کاملاً تازه با Migrationهای Laravel ساخته می‌شود (سازگاری با داده‌های قدیمی Python لازم نیست؛ فقط هش‌های قدیمی رمز عبور `pbkdf2_sha256` هنگام ورود verify و به Argon2id ارتقا پیدا می‌کنند).

قرارداد API دقیقاً مثل قبل است: همان ۵۵ endpoint، همان envelope پاسخ (`{ok:true,...}` و خطای فارسی `{ok:false,error:{code,message,details}}`)، همان احراز با کوکی `mas_session` + هدر `X-CSRF-Token` (و Bearer)، توکن عمومی اتاق، کد ۴کاراکتری سخنران، تایمر با ETag/304، ضبط تکه‌ای (chunk)، آپلود/دانلود/پخش با HTTP Range، واکنش‌ها، QR، گزارش PDF و پنل مدیریت.

## معماری

| نسخهٔ Python | نسخهٔ PHP |
|---|---|
| `mas_app/api/routers/*` | `backend/app/Http/Controllers/Api/*` |
| `mas_app/services/*` | `backend/app/Services/*` |
| `mas_app/schemas/*` | `backend/app/Presenters/MasPresenter.php` + `app/Http/Requests/*` |
| `mas_app/db/models.py` | `backend/app/Models/*` + یک Migration یکپارچه |
| `mas_app/storage/*` | `backend/app/Services/Storage/*` (Local + S3) |
| `mas_app/api/csrf.py` و middlewareهای `main.py` | `backend/app/Http/Middleware/*` |
| `mas_app/config.py` | `backend/config/mas.php` + `App\Support\Settings` |
| ورکر پس‌زمینهٔ cleanup | دستور `mas:maintenance` + سرویس `scheduler` |
| `scripts/create_admin.py` | `php artisan mas:create-admin` |

نکته‌ها: نشست‌ها توکن‌های HMAC هستند (نه Sanctum)؛ واکنش‌ها روی Cache لاراول‌اند (Redis در Docker، چون PHP-FPM چندپردازه‌ای است)؛ گزارش PDF با **mPDF** و فونت Vazirmatn تولید می‌شود و همهٔ متن‌های کاربر escape می‌شوند؛ آپلود جریانی سقف سخت دارد (قطع و پاک‌سازی هنگام عبور از سقف)؛ پخش/دانلود فایل محلی با `BinaryFileResponse` (Range واقعی ۲۰۶) و بک‌اند ابری با استریم برش‌خورده + ۴۱۶ انجام می‌شود.

## اجرا با Docker (پیشنهادی)

```bash
cd newphp
docker compose up -d --build
# برنامه: http://localhost:8080
```

سرویس‌ها: `db` (PostgreSQL 16)، `redis` (کش واکنش‌ها)، `app` (PHP-FPM؛ در entrypoint کلیدها ساخته و Migration اجرا می‌شود)، `scheduler` (چرخهٔ نگهداری هر ۵ دقیقه) و `web` (Nginx: سرو فرانت‌اند + FastCGI برای `/api`، `/health`، `/ready`).

ساخت اولین مدیر (ادمین از ثبت‌نام عمومی ساخته نمی‌شود):

```bash
# ۱) از صفحهٔ ثبت‌نام یک حساب بسازید
# ۲) بعد آن حساب را ارتقا دهید:
docker compose exec app php artisan mas:create-admin USERNAME
```

برای production واقعی این‌ها را در محیط تنظیم کنید: `MAS_SECRET_KEY` (حداقل ۳۲ نویسه)، `APP_KEY`، `DB_PASSWORD`، و پشت HTTPS مقدار `MAS_COOKIE_SECURE=true`. ذخیره‌سازی S3 با `MAS_STORAGE_BACKEND=s3` و متغیرهای `MAS_S3_*` فعال می‌شود (به `.env.example` در `backend/` نگاه کنید).

## اجرای محلی بدون Docker

```bash
cd newphp/backend
composer install
cp .env.example .env   # برای توسعه DB_CONNECTION=sqlite بگذارید
php artisan key:generate
php artisan migrate
php artisan serve       # http://127.0.0.1:8000

cd ../frontend
npm ci
npm run dev             # http://localhost:3000 (پروکسی /api به 8000)
```

## تست‌ها

تست‌های PHPUnit قرارداد API و رگرسیون‌های ممیزی (B-02 تا B-06 و B-11) را پوشش می‌دهند (SQLite حافظه‌ای + کش array):

```bash
cd newphp/backend && php artisan test
# یا داخل Docker:
docker compose run --rm app sh -c "composer install && php artisan test"
```

## تفاوت‌های عمدی با نسخهٔ Python

دو ایرادِ بازِ نسخهٔ Python در این بازنویسی تکرار **نشده‌اند**:

- **B-08:** پاک‌سازی صف فایل‌ها حالا backend ذخیره‌شدهٔ هر آیتم را رعایت می‌کند (هر فایل از همان backendای حذف می‌شود که روی آن ذخیره شده)، نه backend فعلی تنظیمات را.
- **B-11:** نام کاربری‌ای که کلید یکتای آن خالی شود (مثل `___`) هنگام ثبت‌نام با خطای اعتبارسنجی رد می‌شود.

همچنین ETagهای تایمر/حالت عمومی فقط برای سازگاری داخلی 304 هستند و لازم نیست با هش Python برابر باشند، و خطاهای validation به‌جای ۴۲۲ لاراول با همان قالب ۴۰۰ نسخهٔ Python برمی‌گردند.

## ساختار پوشه‌ها

```
newphp/
├── docker-compose.yml
├── backend/          # Laravel 12 — کل API
│   ├── app/ (Controllers, Services, Models, Middleware, Presenters, Exceptions)
│   ├── config/mas.php
│   ├── database/migrations/  # یک Migration برای هر ۱۲ جدول
│   ├── routes/ (api.php, health.php, console.php)
│   ├── storage/fonts/Vazirmatn.ttf
│   └── tests/ (Feature + Unit)
└── frontend/         # همان React/TypeScript نسخهٔ Python، بدون تغییر
```
