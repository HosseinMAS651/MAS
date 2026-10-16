<?php

namespace App\Exceptions;

class QuotaExceededError extends AppError
{
    public int $statusCode = 413;

    public string $errorCode = 'QUOTA_EXCEEDED';

    public string $errorMessage = 'سقف مجاز منبع (تعداد اتاق، ظرفیت یا فضای دیسک) پر شده است.';
}
