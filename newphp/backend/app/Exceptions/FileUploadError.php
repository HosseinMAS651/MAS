<?php

namespace App\Exceptions;

class FileUploadError extends AppError
{
    public int $statusCode = 400;

    public string $errorCode = 'FILE_UPLOAD_ERROR';

    public string $errorMessage = 'خطا در پردازش فایل ارسالی.';
}
