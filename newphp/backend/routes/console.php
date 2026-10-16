<?php

use Illuminate\Support\Facades\Schedule;

// معادل ورکر پس‌زمینهٔ نگهداری در نسخهٔ Python: هر چرخه صف پاک‌سازی فایل‌های
// حذف‌شده و ضبط‌های متروکه را پردازش می‌کند (در کانتینر scheduler اجرا می‌شود).
Schedule::command('mas:maintenance')->everyFiveMinutes()->withoutOverlapping();
