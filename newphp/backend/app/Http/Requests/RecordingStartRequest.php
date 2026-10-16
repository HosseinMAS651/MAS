<?php

namespace App\Http\Requests;

class RecordingStartRequest extends MasFormRequest
{
    public function rules(): array
    {
        return [
            'mime_type' => ['nullable', 'string', 'max:80'],
        ];
    }
}
