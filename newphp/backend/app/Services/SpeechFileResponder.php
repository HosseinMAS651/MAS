<?php

namespace App\Services;

use App\Exceptions\NotFoundError;
use App\Models\SpeechFile;
use App\Services\Storage\StorageBackend;
use App\Support\HttpRange;
use App\Support\RangeNotSatisfiable;
use Symfony\Component\HttpFoundation\BinaryFileResponse;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\HttpFoundation\StreamedResponse;

/**
 * سرو فایل ذخیره‌شده با پشتیبانی کامل Range (رفع B-04):
 * بک‌اند محلی با BinaryFileResponse (۲۰۶ و Accept-Ranges ذاتی Symfony) و
 * بک‌اند ابری با استریم برش‌خورده دستی؛ بازهٔ نامعتبر یعنی ۴۱۶.
 */
class SpeechFileResponder
{
    public function __construct(private readonly StorageBackend $storage)
    {
    }

    /** @param array<string, string> $headers */
    public function respond(
        SpeechFile $file,
        array $headers,
        string $contentType,
        ?string $rangeHeader,
    ): Response {
        $presigned = $this->storage->presignedDownloadUrl($file->storage_key, $file->filename);
        if ($presigned !== null) {
            return new Response('', 303, ['Location' => $presigned]);
        }

        $localPath = $this->storage->localPath($file->storage_key);
        if ($localPath !== null) {
            if (! is_file($localPath)) {
                throw new NotFoundError('فایل روی فضای ذخیره‌سازی یافت نشد.');
            }
            $response = new BinaryFileResponse($localPath);
            $response->setContentDisposition(
                str_contains($headers['Content-Disposition'] ?? '', 'attachment')
                    ? BinaryFileResponse::DISPOSITION_ATTACHMENT
                    : BinaryFileResponse::DISPOSITION_INLINE,
                $file->filename,
            );
            // Content-Disposition خام (filename* UTF-8) مثل نسخهٔ Python حفظ می‌شود.
            foreach ($headers as $name => $value) {
                $response->headers->set($name, $value);
            }
            $response->headers->set('Content-Type', $contentType);
            $response->setAutoEtag();

            return $response;
        }

        $size = $file->size_bytes;
        try {
            $range = HttpRange::parseSingle($rangeHeader, $size);
        } catch (RangeNotSatisfiable) {
            return new Response('', 416, [
                'Content-Range' => "bytes */{$size}",
                'Accept-Ranges' => 'bytes',
            ]);
        }

        $stream = $this->storage->openStream($file->storage_key);
        if ($range === null) {
            return new StreamedResponse(function () use ($stream) {
                $this->pump($stream, 0, PHP_INT_MAX);
            }, 200, [
                ...$headers,
                'Content-Type' => $contentType,
                'Content-Length' => (string) $size,
                'Accept-Ranges' => 'bytes',
            ]);
        }

        [$start, $end] = $range;
        $length = $end - $start + 1;

        return new StreamedResponse(function () use ($stream, $start, $length) {
            $this->pump($stream, $start, $length);
        }, 206, [
            ...$headers,
            'Content-Type' => $contentType,
            'Content-Length' => (string) $length,
            'Content-Range' => "bytes {$start}-{$end}/{$size}",
            'Accept-Ranges' => 'bytes',
        ]);
    }

    /** @param resource $stream */
    private function pump($stream, int $skip, int $length): void
    {
        $remainingSkip = $skip;
        $remaining = $length;
        while (! feof($stream) && $remaining > 0) {
            $chunk = fread($stream, 1024 * 1024);
            if ($chunk === false || $chunk === '') {
                break;
            }
            if ($remainingSkip > 0) {
                if (strlen($chunk) <= $remainingSkip) {
                    $remainingSkip -= strlen($chunk);
                    continue;
                }
                $chunk = substr($chunk, $remainingSkip);
                $remainingSkip = 0;
            }
            $piece = substr($chunk, 0, $remaining);
            $remaining -= strlen($piece);
            echo $piece;
            flush();
        }
        fclose($stream);
    }
}
