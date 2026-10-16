<?php

namespace App\Exceptions;

class ConflictError extends AppError
{
    public int $statusCode = 409;

    public string $errorCode = 'CONFLICT';

    public string $errorMessage = 'تداخل در داده‌ها رخ داده است؛ لطفاً صفحه را تازه‌سازی کنید.';
}
