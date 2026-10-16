<?php

namespace App\Http\Requests;

class RecordingFinishRequest extends MasFormRequest
{
    public function rules(): array
    {
        return [
            'save' => ['nullable', 'boolean'],
        ];
    }
}
