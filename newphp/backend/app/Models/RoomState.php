<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/** وضعیت زندهٔ تایمر اتاق (یک ردیف برای هر اتاق). */
class RoomState extends Model
{
    public $timestamps = false;

    protected $guarded = [];

    protected $casts = [
        'current_index' => 'integer',
        'running' => 'boolean',
        'awaiting_decision' => 'boolean',
        'started_at_ms' => 'integer',
        'elapsed_ms' => 'integer',
        'overtime_ms' => 'integer',
        'updated_at_ms' => 'integer',
        'version' => 'integer',
    ];

    public function room(): BelongsTo
    {
        return $this->belongsTo(Room::class, 'room_id');
    }

    public function currentSpeaker(): BelongsTo
    {
        return $this->belongsTo(Speaker::class, 'current_speaker_id');
    }
}
