<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

/** لاگ ممیزی/امنیتی؛ detail یک رشتهٔ JSON است (مثل نسخهٔ Python). */
class AuditLog extends Model
{
    public $timestamps = false;

    protected $guarded = [];

    protected $casts = [
        'created_at_ms' => 'integer',
    ];
}
