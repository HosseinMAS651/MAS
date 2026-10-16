<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;
use Illuminate\Database\Eloquent\Relations\HasOne;

class Room extends Model
{
    public $timestamps = false;

    protected $guarded = [];

    protected $casts = [
        'capacity' => 'integer',
        'recording_enabled' => 'boolean',
        'live_files_enabled' => 'boolean',
        'speaker_mode_enabled' => 'boolean',
        'speaker_uploads_enabled' => 'boolean',
        'public_enabled' => 'boolean',
        'public_token_created_at_ms' => 'integer',
        'global_seconds' => 'integer',
        'storage_used_bytes' => 'integer',
        'created_at_ms' => 'integer',
        'updated_at_ms' => 'integer',
        'version' => 'integer',
    ];

    public function owner(): BelongsTo
    {
        return $this->belongsTo(User::class, 'owner_id');
    }

    public function speakers(): HasMany
    {
        return $this->hasMany(Speaker::class, 'room_id')->orderBy('order_index');
    }

    public function files(): HasMany
    {
        return $this->hasMany(SpeechFile::class, 'room_id');
    }

    public function state(): HasOne
    {
        return $this->hasOne(RoomState::class, 'room_id');
    }

    public function recordingSessions(): HasMany
    {
        return $this->hasMany(RecordingSession::class, 'room_id');
    }
}
