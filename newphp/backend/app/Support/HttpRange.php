<?php

namespace App\Support;

/**
 * پارس Range تک‌بخشی HTTP (معادل parse_single_range در storage/base.py
 * نسخهٔ Python — رفع B-04). برای بک‌اندهای غیرمحلی که BinaryFileResponse
 * نمی‌توانند بدهند استفاده می‌شود؛ مسیر محلی از خود Symfony استفاده می‌کند.
 */
class HttpRange
{
    /**
     * @return array{0: int, 1: int}|null بازهٔ شامل ابتدا و انتها؛ null یعنی
     *         هدر ناموجود/نامعتبر/ چندبخشی است و باید بدنهٔ کامل سرو شود.
     *
     * @throws RangeNotSatisfiable وقتی بازه معتبر ولی خارج از اندازهٔ فایل است.
     */
    public static function parseSingle(?string $rangeHeader, int $size): ?array
    {
        if ($rangeHeader === null || $rangeHeader === '') {
            return null;
        }
        $eq = strpos($rangeHeader, '=');
        if ($eq === false) {
            return null;
        }
        if (strtolower(trim(substr($rangeHeader, 0, $eq))) !== 'bytes') {
            return null;
        }
        $spec = trim(substr($rangeHeader, $eq + 1));
        if (str_contains($spec, ',')) {
            return null; // چندبخشی پشتیبانی نمی‌شود؛ بدنهٔ کامل مجاز است.
        }
        $dash = strpos($spec, '-');
        if ($dash === false) {
            return null;
        }
        $startText = trim(substr($spec, 0, $dash));
        $endText = trim(substr($spec, $dash + 1));

        if ($startText === '') {
            if (! is_numeric($endText)) {
                return null;
            }
            $suffix = (int) $endText;
            if ($suffix <= 0) {
                throw new RangeNotSatisfiable;
            }
            $start = max(0, $size - $suffix);
            $end = $size - 1;
        } else {
            if (! is_numeric($startText) || ($endText !== '' && ! is_numeric($endText))) {
                return null;
            }
            $start = (int) $startText;
            $end = $endText === '' ? $size - 1 : (int) $endText;
        }

        if ($start >= $size || $end < $start) {
            throw new RangeNotSatisfiable;
        }

        return [$start, min($end, $size - 1)];
    }
}
