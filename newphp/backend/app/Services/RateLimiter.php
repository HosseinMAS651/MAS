<?php

namespace App\Services;

use App\Exceptions\RateLimitExceededError;
use App\Models\RateLimitBucket;
use App\Support\Mas;
use Illuminate\Support\Facades\DB;

/**
 * محدودساز نرخ اتمیک مبتنی بر دیتابیس (معادل rate_limiter.py).
 * افزایش شمارنده در تراکنش جدا commit می‌شود تا حتی وقتی درخواست با ۴۲۹
 * رد می‌شود، وضعیت بلاک‌شدن پایدار بماند.
 */
class RateLimiter
{
    public static function checkAndIncrement(
        string $bucketKey,
        string $action,
        int $maxAttempts,
        int $windowSeconds,
    ): void {
        $retryAfter = DB::transaction(function () use ($bucketKey, $action, $maxAttempts, $windowSeconds) {
            $now = Mas::nowMs();
            $windowMs = $windowSeconds * 1000;

            $bucket = RateLimitBucket::query()
                ->where('bucket_key', $bucketKey)
                ->lockForUpdate()
                ->first();

            if ($bucket === null) {
                RateLimitBucket::create([
                    'bucket_key' => $bucketKey,
                    'action' => $action,
                    'count' => 1,
                    'window_started_at_ms' => $now,
                    'blocked_until_ms' => 0,
                ]);

                return null;
            }

            if ($bucket->blocked_until_ms > $now) {
                return max(1, intdiv($bucket->blocked_until_ms - $now + 999, 1000));
            }

            if ($now - $bucket->window_started_at_ms >= $windowMs) {
                $bucket->window_started_at_ms = $now;
                $bucket->count = 1;
                $bucket->blocked_until_ms = 0;
                $bucket->action = $action;
                $bucket->save();

                return null;
            }

            if ($bucket->count >= $maxAttempts) {
                $bucket->blocked_until_ms = $bucket->window_started_at_ms + $windowMs;
                $bucket->save();

                return max(1, intdiv($bucket->blocked_until_ms - $now + 999, 1000));
            }

            $bucket->count += 1;
            $bucket->action = $action;
            $bucket->save();

            return null;
        });

        if ($retryAfter !== null) {
            throw new RateLimitExceededError(retryAfterSeconds: $retryAfter);
        }
    }

    public static function reset(string $bucketKey): void
    {
        RateLimitBucket::query()->where('bucket_key', $bucketKey)->delete();
    }
}
