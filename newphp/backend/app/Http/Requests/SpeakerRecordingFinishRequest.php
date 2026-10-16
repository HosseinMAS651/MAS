<?php

namespace App\Http\Requests;

class SpeakerRecordingFinishRequest extends MasFormRequest
{
    public function rules(): array
    {
        return [
            'session_id' => ['required', 'integer', 'min:1'],
            'save' => ['nullable', 'boolean'],
        ];
    }
}
