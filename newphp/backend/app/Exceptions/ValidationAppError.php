<?php

namespace App\Exceptions;

class ValidationAppError extends AppError
{
    public int $statusCode = 400;

    public string $errorCode = 'VALIDATION_ERROR';

    public string $errorMessage = 'اطلاعات ارسالی نامعتبر است.';
}
