<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasMany;

/** کاربر سامانه (مالک اتاق یا مدیر). زمان‌ها epoch میلی‌ثانیه‌اند. */
class User extends Model
{
    public $timestamps = false;

    protected $guarded = [];

    protected $casts = [
        'age' => 'integer',
        'profile_completed' => 'boolean',
        'is_active' => 'boolean',
        'storage_used_bytes' => 'integer',
        'failed_login_count' => 'integer',
        'locked_until_ms' => 'integer',
        'created_at_ms' => 'integer',
        'updated_at_ms' => 'integer',
        'last_login_at_ms' => 'integer',
        'version' => 'integer',
    ];

    public function rooms(): HasMany
    {
        return $this->hasMany(Room::class, 'owner_id');
    }

    public function sessions(): HasMany
    {
        return $this->hasMany(AuthSession::class, 'user_id');
    }
}
