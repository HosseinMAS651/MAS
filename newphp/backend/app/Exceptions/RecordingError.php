<?php

namespace App\Exceptions;

class RecordingError extends AppError
{
    public int $statusCode = 400;

    public string $errorCode = 'RECORDING_ERROR';

    public string $errorMessage = 'عملیات ضبط با خطا مواجه شد.';
}
