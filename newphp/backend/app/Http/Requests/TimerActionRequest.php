<?php

namespace App\Http\Requests;

use Illuminate\Validation\Rule;

class TimerActionRequest extends MasFormRequest
{
    public function rules(): array
    {
        return [
            'action' => ['required', Rule::in([
                'start', 'pause', 'resume', 'finish', 'continue_overtime',
                'finish_overtime', 'reset', 'goto',
            ])],
            'speaker_id' => ['nullable', 'integer'],
            'expected_version' => ['nullable', 'integer', 'min:1'],
        ];
    }
}
