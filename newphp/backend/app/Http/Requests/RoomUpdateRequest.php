<?php

namespace App\Http\Requests;

class RoomUpdateRequest extends RoomStoreRequest
{
    public function rules(): array
    {
        return [
            ...parent::rules(),
            'confirm_shrink' => ['nullable', 'boolean'],
        ];
    }
}
