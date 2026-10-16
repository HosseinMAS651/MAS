<?php

namespace App\Http\Requests;

class IssueRecoveryCodeRequest extends MasFormRequest
{
    public function rules(): array
    {
        return [
            'current_password' => ['required', 'string', 'min:1', 'max:128'],
        ];
    }
}
