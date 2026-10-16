<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/** فایل مشترک، فایل اختصاصی سخنران، یا ضبط صوت ذخیره‌شده. */
class SpeechFile extends Model
{
    public $timestamps = false;

    protected $guarded = [];

    protected $casts = [
        'size_bytes' => 'integer',
        'duration_ms' => 'integer',
        'created_at_ms' => 'integer',
        'updated_at_ms' => 'integer',
    ];

    public function room(): BelongsTo
    {
        return $this->belongsTo(Room::class, 'room_id');
    }

    public function speaker(): BelongsTo
    {
        return $this->belongsTo(Speaker::class, 'speaker_id');
    }
}
