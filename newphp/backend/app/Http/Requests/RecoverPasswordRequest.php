<?php

namespace App\Http\Requests;

class RecoverPasswordRequest extends MasFormRequest
{
    public function rules(): array
    {
        return [
            'username' => ['required', 'string', 'min:1', 'max:64'],
            'recovery_code' => ['required', 'string', 'min:1', 'max:64'],
            'new_password' => ['required', 'string', 'min:8', 'max:128'],
        ];
    }
}
