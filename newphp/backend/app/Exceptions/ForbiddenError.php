<?php

namespace App\Exceptions;

class ForbiddenError extends AppError
{
    public int $statusCode = 403;

    public string $errorCode = 'FORBIDDEN';

    public string $errorMessage = 'شما اجازهٔ دسترسی به این بخش را ندارید.';
}
