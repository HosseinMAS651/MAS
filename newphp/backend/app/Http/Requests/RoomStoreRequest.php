<?php

namespace App\Http\Requests;

use App\Support\Mas;
use Illuminate\Validation\Rule;

class RoomStoreRequest extends MasFormRequest
{
    protected function prepareForValidation(): void
    {
        $this->merge([
            'name' => Mas::normalizePersianText((string) $this->input('name', '')),
            'description' => Mas::normalizePersianText((string) $this->input('description', '')),
        ]);
    }

    public function rules(): array
    {
        return [
            // سقف اسکیما ۱۰۰۰ است؛ بازهٔ واقعی سرور در RoomService::validateCapacity اعمال می‌شود (B-05).
            'name' => ['required', 'string', 'min:1', 'max:160'],
            'capacity' => ['nullable', 'integer', 'min:1', 'max:1000'],
            'description' => ['nullable', 'string', 'max:20000'],
            'recording_enabled' => ['nullable', 'boolean'],
            'live_files_enabled' => ['nullable', 'boolean'],
            'speaker_mode_enabled' => ['nullable', 'boolean'],
            'speaker_uploads_enabled' => ['nullable', 'boolean'],
            'timing_mode' => ['nullable', Rule::in(['global', 'individual'])],
            'global_seconds' => ['nullable', 'integer', 'min:10', 'max:86400'],
            'order_mode' => ['nullable', Rule::in(['manual', 'alpha', 'age'])],
            'public_enabled' => ['nullable', 'boolean'],
        ];
    }
}
