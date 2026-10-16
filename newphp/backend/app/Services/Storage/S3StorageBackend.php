<?php

namespace App\Services\Storage;

use App\Exceptions\NotFoundError;
use App\Support\Settings;
use Illuminate\Support\Facades\Storage;

/**
 * بک‌اند S3 (معادل storage/s3.py) روی دیسک s3 لاراول (Flysystem + AWS SDK).
 * کلیدها با MAS_S3_PREFIX پیشوند می‌گیرند و URL امضاشده فقط وقتی
 * MAS_S3_USE_PRESIGNED_DOWNLOAD فعال باشد صادر می‌شود.
 */
class S3StorageBackend implements StorageBackend
{
    public function __construct(private readonly Settings $settings)
    {
    }

    private function disk(): \Illuminate\Contracts\Filesystem\Filesystem
    {
        return Storage::disk('s3');
    }

    private function prefixed(string $key): string
    {
        $prefix = trim((string) $this->settings->get('s3_prefix', 'mas/'), '/');

        return $prefix === '' ? ltrim($key, '/') : $prefix.'/'.ltrim($key, '/');
    }

    public function saveBytes(string $key, string $data): array
    {
        if ($data === '') {
            throw new \RuntimeException('empty data');
        }
        $this->disk()->put($this->prefixed($key), $data);

        return [strlen($data), hash('sha256', $data)];
    }

    public function saveStream(string $key, $stream, ?int $limitBytes = null): array
    {
        // برای محاسبهٔ sha256 و اندازه، استریم یک بار خوانده و هم‌زمان hash می‌شود.
        $ctx = hash_init('sha256');
        $size = 0;
        $tmp = tmpfile();
        if ($tmp === false) {
            throw new \RuntimeException('cannot create temp buffer');
        }
        while (! feof($stream)) {
            $chunk = fread($stream, 1024 * 1024);
            if ($chunk === false) {
                fclose($tmp);
                throw new \RuntimeException('read error on upload stream');
            }
            if ($chunk === '') {
                continue;
            }
            $size += strlen($chunk);
            if ($limitBytes !== null && $size > $limitBytes) {
                fclose($tmp);
                throw new \App\Exceptions\QuotaExceededError('حجم فایل از سقف مجاز بیشتر است.');
            }
            fwrite($tmp, $chunk);
            hash_update($ctx, $chunk);
        }
        if ($size <= 0) {
            fclose($tmp);
            throw new \RuntimeException('empty data');
        }
        rewind($tmp);
        $this->disk()->put($this->prefixed($key), $tmp);
        fclose($tmp);

        return [$size, hash_final($ctx)];
    }

    public function delete(string $key): void
    {
        $this->disk()->delete($this->prefixed($key));
    }

    public function openStream(string $key)
    {
        $prefixed = $this->prefixed($key);
        if (! $this->disk()->exists($prefixed)) {
            throw new NotFoundError('فایل روی فضای ذخیره‌سازی یافت نشد.');
        }
        $stream = $this->disk()->readStream($prefixed);
        if ($stream === false || $stream === null) {
            throw new NotFoundError('فایل روی فضای ذخیره‌سازی یافت نشد.');
        }

        return $stream;
    }

    public function assembleChunks(string $targetKey, array $chunkKeys): array
    {
        if ($chunkKeys === []) {
            throw new \RuntimeException('no chunks to assemble');
        }
        $tmp = tmpfile();
        if ($tmp === false) {
            throw new \RuntimeException('cannot create temp buffer');
        }
        $ctx = hash_init('sha256');
        $size = 0;
        foreach ($chunkKeys as $chunkKey) {
            $in = $this->openStream($chunkKey);
            while (! feof($in)) {
                $data = fread($in, 1024 * 1024);
                if ($data === false || $data === '') {
                    continue;
                }
                fwrite($tmp, $data);
                hash_update($ctx, $data);
                $size += strlen($data);
            }
            fclose($in);
        }
        if ($size <= 0) {
            fclose($tmp);
            throw new \RuntimeException('no chunks to assemble');
        }
        rewind($tmp);
        $this->disk()->put($this->prefixed($targetKey), $tmp);
        fclose($tmp);

        return [$size, hash_final($ctx)];
    }

    public function checkHealth(): array
    {
        try {
            $probe = $this->prefixed('.healthcheck');
            $this->disk()->put($probe, 'ok');
            $this->disk()->delete($probe);

            return [true, 'ok'];
        } catch (\Throwable $e) {
            return [false, mb_substr($e->getMessage(), 0, 250)];
        }
    }

    public function presignedDownloadUrl(string $key, string $filename): ?string
    {
        if (! $this->settings->get('s3_use_presigned_download', false)) {
            return null;
        }
        $ttl = (int) $this->settings->get('s3_presigned_ttl_seconds', 900);

        return $this->disk()->temporaryUrl(
            $this->prefixed($key),
            now()->addSeconds($ttl),
            ['ResponseContentDisposition' => 'attachment; filename="'.addslashes($filename).'"'],
        );
    }

    public function localPath(string $key): ?string
    {
        return null;
    }

    public function availableBytes(): ?int
    {
        return null;
    }
}
