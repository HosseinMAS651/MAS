<?php

namespace App\Http\Requests;

class ChangePasswordRequest extends MasFormRequest
{
    public function rules(): array
    {
        return [
            'current_password' => ['required', 'string', 'min:1', 'max:128'],
            'new_password' => ['required', 'string', 'min:8', 'max:128'],
        ];
    }
}
