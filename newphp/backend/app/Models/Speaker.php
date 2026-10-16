<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;
use Illuminate\Database\Eloquent\Relations\HasOne;

class Speaker extends Model
{
    public $timestamps = false;

    protected $guarded = [];

    protected $casts = [
        'order_index' => 'integer',
        'age' => 'integer',
        'speaking_seconds' => 'integer',
        'is_finished' => 'boolean',
        'finished_at_ms' => 'integer',
        'presence_last_seen_at_ms' => 'integer',
        'created_at_ms' => 'integer',
        'updated_at_ms' => 'integer',
    ];

    public function room(): BelongsTo
    {
        return $this->belongsTo(Room::class, 'room_id');
    }

    public function files(): HasMany
    {
        return $this->hasMany(SpeechFile::class, 'speaker_id');
    }

    public function timer(): HasOne
    {
        return $this->hasOne(SpeakerTimerState::class, 'speaker_id');
    }

    public function recordingSessions(): HasMany
    {
        return $this->hasMany(RecordingSession::class, 'speaker_id');
    }
}
