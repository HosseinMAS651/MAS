<?php

namespace App\Http\Requests;

class SpeakerHeartbeatRequest extends MasFormRequest
{
    public function rules(): array
    {
        return [
            'microphone_ready' => ['nullable', 'boolean'],
        ];
    }
}
