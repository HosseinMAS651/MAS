<?php

namespace App\Exceptions;

class NotFoundError extends AppError
{
    public int $statusCode = 404;

    public string $errorCode = 'NOT_FOUND';

    public string $errorMessage = 'موردی با این مشخصات یافت نشد.';
}
