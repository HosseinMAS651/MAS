<?php

namespace App\Exceptions;

class UnauthorizedError extends AppError
{
    public int $statusCode = 401;

    public string $errorCode = 'UNAUTHORIZED';

    public string $errorMessage = 'لطفاً ابتدا وارد حساب کاربری خود شوید.';
}
