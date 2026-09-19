# Changelog — MAS Rewrite

## Rewrite

- بازنویسی ساختار Backend، Storage، Auth، Timer و Frontend
- تایمر میلی‌ثانیه‌ای با interpolation سمت مرورگر برای کاهش پرش و ناهماهنگی بصری
- Timer state مستقل برای هر سخنران
- Overtime واقعی و ثبت‌شده در سمت سرور
- اعلان پایان زمان + انتخاب ادامه یا اتمام
- فریزشدن سخنران تمام‌شده بدون حذف
- امکان بازگشت به سخنران فریز‌شده با Previous یا انتخاب مستقیم از فهرست
- دکمه اتمام دستی
- حذف سخنران در حین پخش + کاهش ظرفیت + انتخاب خودکار سخنران بعدی فعال
- تغییر رمز عبور + باطل‌شدن همه Sessionهای قبلی
- Login/Register CSRF
- Session امن با توکن تصادفی و نگهداری Hash در DB
- Rate Limit پایدار در DB
- اصلاح XSS/Content-Disposition/Path Traversal/CSRF
- محدودسازی نوع فایل ضبط
- fallback ذخیره محلی ضبط در صورت شکست Upload
- reconciliation برای فایل‌های orphan
- PostgreSQL-compatible storage quota update
- migration/repair برای داده‌های قدیمی و ایجاد indexهای یکتا
- test suite با ۲۰ تست regression/integration
