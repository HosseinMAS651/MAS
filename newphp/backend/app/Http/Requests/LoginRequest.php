<?php

namespace App\Http\Requests;

class LoginRequest extends MasFormRequest
{
    public function rules(): array
    {
        return [
            'username' => ['required', 'string', 'min:1', 'max:64'],
            'password' => ['required', 'string', 'min:1', 'max:128'],
        ];
    }
}
