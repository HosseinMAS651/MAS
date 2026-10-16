<?php

namespace App\Support;

/**
 * ابزارهای متنی/زمانی معادل mas_app/core/security.py (بخش نرمال‌سازی) و
 * mas_app/core/timeutil.py. همهٔ زمان‌ها epoch میلی‌ثانیهٔ UTC هستند.
 */
class Mas
{
    public static function nowMs(): int
    {
        return (int) floor(microtime(true) * 1000);
    }

    /** مدت سپری‌شده؛ هرگز منفی نمی‌شود (ساعت سرور اگر عقب برگردد تایمر عقب نمی‌رود). */
    public static function nonNegativeDelta(?int $startedAtMs, ?int $nowMs = null): int
    {
        if (! $startedAtMs) {
            return 0;
        }
        $delta = ($nowMs ?? self::nowMs()) - $startedAtMs;

        return max(0, $delta);
    }

    private const ARABIC_TO_PERSIAN = [
        'ي' => 'ی', 'ى' => 'ی', 'ك' => 'ک', 'ة' => 'ه', 'ۀ' => 'ه',
        '۰' => '0', '۱' => '1', '۲' => '2', '۳' => '3', '۴' => '4',
        '۵' => '5', '۶' => '6', '۷' => '7', '۸' => '8', '۹' => '9',
        '٠' => '0', '١' => '1', '٢' => '2', '٣' => '3', '٤' => '4',
        '٥' => '5', '٦' => '6', '٧' => '7', '٨' => '8', '٩' => '9',
    ];

    /** یکسان‌سازی حروف و ارقام عربی/فارسی و حذف نویسه‌های کنترلی. */
    public static function normalizePersianText(?string $text): string
    {
        if ($text === null || $text === '') {
            return '';
        }
        $normalized = \Normalizer::normalize($text, \Normalizer::NFC);
        if ($normalized === false) {
            $normalized = $text;
        }
        $translated = strtr($normalized, self::ARABIC_TO_PERSIAN);
        // حذف کاراکترهای کنترلی (دستهٔ C در یونیکد) به‌جز فاصله و خط جدید
        $cleaned = preg_replace('/[^\P{C}\n\r\t ]/u', '', $translated);

        return trim($cleaned ?? $translated);
    }

    /** نرمال‌سازی نام کاربری برای نمایش (فاصله‌های اضافی حذف می‌شود). */
    public static function normalizeUsername(?string $raw): string
    {
        $clean = self::normalizePersianText($raw ?? '');

        return preg_replace('/\s+/u', ' ', $clean) ?? $clean;
    }

    /**
     * کلید یکتایی/جست‌وجوی نام کاربری (بی‌حساسیت به بزرگی/کوچکی و نویسه‌های معادل).
     * توجه (B-11): نام‌هایی مثل «___» یا «---» به کلید خالی فرو می‌ریزند؛ لایهٔ
     * اعتبارسنجی ثبت‌نام کلید خالی را رد می‌کند تا دو حساب روی یک کلید نیفتند.
     */
    public static function usernameToKey(?string $username): string
    {
        $clean = self::normalizePersianText($username ?? '');
        $clean = mb_strtolower($clean);

        return str_replace([' ', '_', '-'], '', $clean);
    }

    /** پاک‌سازی نام فایل برای نمایش امن (حفظ حروف فارسی، حذف نویسه‌های خطرناک مسیر). */
    public static function sanitizeFilename(?string $name, string $fallback = 'file'): string
    {
        if ($name === null || $name === '') {
            return $fallback;
        }
        $clean = self::normalizePersianText($name);
        $safe = preg_replace('/[\\\\\/\*\?:"<>|\x00-\x1F]/u', '', $clean) ?? '';
        $safe = preg_replace('/\.{2,}/', '.', $safe) ?? $safe; // جلوگیری از path traversal با نقطه‌های متوالی
        $safe = trim($safe, ' .');
        if ($safe === '') {
            return $fallback;
        }

        return mb_substr($safe, 0, 180);
    }

    /** قالب‌بندی میلی‌ثانیه به «دقیقه:ثانیه» برای گزارش PDF. */
    public static function formatMsToMinSec(int $ms): string
    {
        $totalSeconds = intdiv(max(0, $ms), 1000);

        return sprintf('%02d:%02d', intdiv($totalSeconds, 60), $totalSeconds % 60);
    }
}
