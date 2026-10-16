<?php

namespace App\Http\Requests;

use Illuminate\Validation\Rule;

class UpdateProfileRequest extends MasFormRequest
{
    public function rules(): array
    {
        return [
            'account_name' => ['nullable', 'string', 'max:120'],
            'age' => ['nullable', 'integer', 'min:1', 'max:120'],
            'job' => ['nullable', 'string', 'max:120'],
            'timezone' => ['nullable', 'string', 'max:64', Rule::in(timezone_identifiers_list())],
            'calendar' => ['nullable', Rule::in(['jalali', 'gregorian'])],
        ];
    }
}
