<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

/** سطل محدودسازی نرخ مبتنی بر دیتابیس (اتمیک، مستقل از کش). */
class RateLimitBucket extends Model
{
    public $timestamps = false;

    protected $guarded = [];

    protected $casts = [
        'count' => 'integer',
        'window_started_at_ms' => 'integer',
        'blocked_until_ms' => 'integer',
    ];
}
