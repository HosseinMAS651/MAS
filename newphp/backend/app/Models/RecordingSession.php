<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

/** نشست ضبط تکه‌ای؛ تکه‌ها به‌ترتیب seq ذخیره و در پایان مونتاژ می‌شوند. */
class RecordingSession extends Model
{
    public $timestamps = false;

    protected $guarded = [];

    protected $casts = [
        'chunk_seq' => 'integer',
        'bytes_received' => 'integer',
        'recorded_ms' => 'integer',
        'active_since_ms' => 'integer',
        'started_at_ms' => 'integer',
        'last_chunk_at_ms' => 'integer',
        'ended_at_ms' => 'integer',
        'version' => 'integer',
    ];

    public function room(): BelongsTo
    {
        return $this->belongsTo(Room::class, 'room_id');
    }

    public function speaker(): BelongsTo
    {
        return $this->belongsTo(Speaker::class, 'speaker_id');
    }

    public function finalFile(): BelongsTo
    {
        return $this->belongsTo(SpeechFile::class, 'final_file_id');
    }

    public function chunks(): HasMany
    {
        return $this->hasMany(RecordingChunk::class, 'session_id')->orderBy('seq');
    }
}
