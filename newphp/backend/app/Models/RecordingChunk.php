<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class RecordingChunk extends Model
{
    public $timestamps = false;

    protected $guarded = [];

    protected $casts = [
        'seq' => 'integer',
        'size_bytes' => 'integer',
        'created_at_ms' => 'integer',
    ];

    public function session(): BelongsTo
    {
        return $this->belongsTo(RecordingSession::class, 'session_id');
    }
}
