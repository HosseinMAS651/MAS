<?php

namespace App\Http\Requests;

class FileReviewRequest extends MasFormRequest
{
    public function rules(): array
    {
        return [
            'approved' => ['required', 'boolean'],
        ];
    }
}
