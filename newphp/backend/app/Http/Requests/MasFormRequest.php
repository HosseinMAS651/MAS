<?php

namespace App\Http\Requests;

use Illuminate\Contracts\Validation\Validator;
use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Validation\ValidationException;

/**
 * پایهٔ همهٔ فرم‌ریکوئست‌ها؛ خطای اعتبارسنجی به‌صورت ValidationException
 * پرتاب می‌شود تا هندلر مرکزی آن را به همان قالب ۴۰۰ نسخهٔ Python تبدیل کند:
 * {"ok": false, "error": {"code": "VALIDATION_ERROR", ...details:{field, errors}}}
 */
abstract class MasFormRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    protected function failedValidation(Validator $validator): void
    {
        throw new ValidationException($validator);
    }
}
