<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/** نشست ورود؛ فقط هش HMAC توکن و CSRF نگه داشته می‌شود، هرگز مقدار خام. */
class AuthSession extends Model
{
    public $timestamps = false;

    protected $guarded = [];

    protected $casts = [
        'created_at_ms' => 'integer',
        'expires_at_ms' => 'integer',
        'last_seen_at_ms' => 'integer',
    ];

    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class, 'user_id');
    }
}
