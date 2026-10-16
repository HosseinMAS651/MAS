<?php

namespace App\Http\Requests;

use App\Support\Mas;
use Illuminate\Validation\Rule;

class RegisterRequest extends MasFormRequest
{
    protected function prepareForValidation(): void
    {
        $this->merge([
            'username' => Mas::normalizeUsername((string) $this->input('username', '')),
        ]);
    }

    public function rules(): array
    {
        return [
            'username' => ['required', 'string', 'min:3', 'max:32'],
            'password' => ['required', 'string', 'min:8', 'max:128'],
            'account_name' => ['nullable', 'string', 'max:120'],
            'age' => ['nullable', 'integer', 'min:1', 'max:120'],
            'job' => ['nullable', 'string', 'max:120'],
            'timezone' => ['nullable', 'string', 'max:64', Rule::in(timezone_identifiers_list())],
            'calendar' => ['nullable', Rule::in(['jalali', 'gregorian'])],
        ];
    }
}
