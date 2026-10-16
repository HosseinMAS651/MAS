<?php

namespace App\Http\Requests;

use App\Support\Mas;
use Illuminate\Validation\Rule;

class SpeakerUpdateRequest extends MasFormRequest
{
    protected function prepareForValidation(): void
    {
        $this->merge([
            'name' => Mas::normalizePersianText((string) $this->input('name', '')),
            'description' => Mas::normalizePersianText((string) $this->input('description', '')),
            'gender' => strtolower(trim((string) $this->input('gender', ''))),
        ]);
    }

    public function rules(): array
    {
        return [
            'name' => ['nullable', 'string', 'max:120'],
            'gender' => ['nullable', Rule::in(['', 'male', 'female', 'other'])],
            'age' => ['nullable', 'integer', 'min:1', 'max:120'],
            'description' => ['nullable', 'string', 'max:20000'],
            'speaking_seconds' => ['nullable', 'integer', 'min:10', 'max:86400'],
        ];
    }
}
