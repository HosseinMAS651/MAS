<?php

namespace App\Exceptions;

class RateLimitExceededError extends AppError
{
    public int $statusCode = 429;

    public string $errorCode = 'RATE_LIMITED';

    public string $errorMessage = 'تعداد درخواست‌های شما بیش از حد مجاز است؛ لطفاً کمی بعد دوباره تلاش کنید.';

    public int $retryAfterSeconds = 60;

    /** @param array<string, mixed> $details */
    public function __construct(?string $message = null, int $retryAfterSeconds = 60, array $details = [])
    {
        $this->retryAfterSeconds = $retryAfterSeconds;
        parent::__construct(
            $message,
            code: 'RATE_LIMITED',
            details: ['retry_after_seconds' => $retryAfterSeconds, ...$details],
            statusCode: 429,
        );
    }
}
