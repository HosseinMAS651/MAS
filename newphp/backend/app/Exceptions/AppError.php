<?php

namespace App\Exceptions;

use Exception;

/**
 * پایهٔ همهٔ خطاهای کنترل‌شدهٔ دامنه؛ خروجی همیشه قالب استاندارد
 * {"ok": false, "error": {"code", "message", "details"}} است.
 */
class AppError extends Exception
{
    public int $statusCode = 400;

    public string $errorCode = 'BAD_REQUEST';

    public string $errorMessage = 'درخواست نامعتبر است.';

    /** @var array<string, mixed> */
    public array $details = [];

    /** @param array<string, mixed> $details */
    public function __construct(
        ?string $message = null,
        ?string $code = null,
        array $details = [],
        ?int $statusCode = null,
        ?\Throwable $previous = null,
    ) {
        if ($message !== null) {
            $this->errorMessage = $message;
        }
        if ($code !== null) {
            $this->errorCode = $code;
        }
        if ($statusCode !== null) {
            $this->statusCode = $statusCode;
        }
        $this->details = $details;
        parent::__construct($this->errorMessage, 0, $previous);
    }

    /** @return array<string, mixed> */
    public function toArray(): array
    {
        return [
            'ok' => false,
            'error' => [
                'code' => $this->errorCode,
                'message' => $this->errorMessage,
                'details' => $this->details,
            ],
        ];
    }
}
