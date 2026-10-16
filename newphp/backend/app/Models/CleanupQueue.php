<?php

namespace App\Models;

use App\Support\Mas;
use Illuminate\Database\Eloquent\Model;

/**
 * صف حذف فیزیکی اشیای ذخیره‌سازی؛ یکتا بر اساس (backend, storage_key) تا
 * ثبت چندبارهٔ یک فایل بی‌اثر و امن باشد (معادل cleanup_queue.py).
 */
class CleanupQueue extends Model
{
    protected $table = 'cleanup_queue';

    public $timestamps = false;

    protected $guarded = [];

    protected $casts = [
        'attempts' => 'integer',
        'next_attempt_at_ms' => 'integer',
        'created_at_ms' => 'integer',
    ];

    /** ثبت idempotent یک شیء برای حذف پس‌زمینه. */
    public static function enqueue(string $backend, string $storageKey, string $reason): self
    {
        $item = self::query()->firstOrCreate(
            ['backend' => $backend, 'storage_key' => $storageKey],
            [
                'reason' => mb_substr($reason, 0, 32),
                'attempts' => 0,
                'next_attempt_at_ms' => Mas::nowMs(),
                'last_error' => '',
                'created_at_ms' => Mas::nowMs(),
            ],
        );
        if ($item->reason === '') {
            $item->reason = mb_substr($reason, 0, 32);
            $item->save();
        }

        return $item;
    }
}
