<?php

namespace App\Http\Requests;

class SpeakerReorderRequest extends MasFormRequest
{
    public function rules(): array
    {
        return [
            'speaker_ids' => ['required', 'array', 'min:1'],
            'speaker_ids.*' => ['integer'],
        ];
    }
}
