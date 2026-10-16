<?php

namespace App\Http\Requests;

class SpeakerEnterRequest extends MasFormRequest
{
    public function rules(): array
    {
        return [
            'code' => ['required', 'string', 'min:1', 'max:16'],
        ];
    }
}
