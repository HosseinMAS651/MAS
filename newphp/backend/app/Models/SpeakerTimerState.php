<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/** زمان انباشتهٔ هر سخنران (مستقل از وضعیت جاری اتاق). */
class SpeakerTimerState extends Model
{
    public $timestamps = false;

    protected $guarded = [];

    protected $casts = [
        'elapsed_ms' => 'integer',
        'overtime_ms' => 'integer',
        'started_at_ms' => 'integer',
        'updated_at_ms' => 'integer',
        'version' => 'integer',
    ];

    public function speaker(): BelongsTo
    {
        return $this->belongsTo(Speaker::class, 'speaker_id');
    }
}
