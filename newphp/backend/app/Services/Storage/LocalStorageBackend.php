<?php

namespace App\Services\Storage;

use RuntimeException;

/**
 * بک‌اند دیسک محلی (معادل storage/local.py): نوشتن اتمیک با فایل موقت +
 * rename، مسیر امن داخل ریشه، مونتاژ تکه‌ها و گزارش فضای آزاد.
 */
class LocalStorageBackend implements StorageBackend
{
    private string $root;

    public function __construct(string $root)
    {
        if (! is_dir($root)) {
            mkdir($root, 0775, true);
        }
        $real = realpath($root);
        $this->root = $real !== false ? $real : $root;
    }

    /** مسیر امن داخل ریشه؛ هر کلیدی که بیرون بزند رد می‌شود. */
    public function safePath(string $key): string
    {
        $key = str_replace('\\', '/', $key);
        $key = ltrim($key, '/');
        $path = $this->root.'/'. $key;
        // نرمال‌سازی قطعه‌های . و .. بدون نیاز به وجود فایل
        $parts = [];
        foreach (explode('/', $path) as $part) {
            if ($part === '' || $part === '.') {
                continue;
            }
            if ($part === '..') {
                array_pop($parts);
                continue;
            }
            $parts[] = $part;
        }
        $normalized = '/'.implode('/', $parts);
        if ($normalized !== $this->root && ! str_starts_with($normalized, $this->root.'/')) {
            throw new RuntimeException('storage key خارج از محدودهٔ storage است');
        }

        return $normalized;
    }

    public function saveBytes(string $key, string $data): array
    {
        if ($data === '') {
            throw new RuntimeException('empty data');
        }
        $path = $this->safePath($key);
        $this->ensureParent($path);
        $tmp = $path.'.tmp';
        file_put_contents($tmp, $data, LOCK_EX);
        rename($tmp, $path);

        return [strlen($data), hash('sha256', $data)];
    }

    public function saveStream(string $key, $stream, ?int $limitBytes = null): array
    {
        $path = $this->safePath($key);
        $this->ensureParent($path);
        $tmp = $path.'.tmp';
        $out = fopen($tmp, 'wb');
        if ($out === false) {
            throw new RuntimeException('cannot open temp file for writing');
        }
        $ctx = hash_init('sha256');
        $size = 0;
        try {
            while (! feof($stream)) {
                $chunk = fread($stream, 1024 * 1024);
                if ($chunk === false) {
                    throw new RuntimeException('read error on upload stream');
                }
                if ($chunk === '') {
                    continue;
                }
                $size += strlen($chunk);
                if ($limitBytes !== null && $size > $limitBytes) {
                    throw new \App\Exceptions\QuotaExceededError('حجم فایل از سقف مجاز بیشتر است.');
                }
                fwrite($out, $chunk);
                hash_update($ctx, $chunk);
            }
            fclose($out);
            if ($size <= 0) {
                throw new RuntimeException('empty data');
            }
            rename($tmp, $path);
        } catch (\Throwable $e) {
            if (is_resource($out)) {
                fclose($out);
            }
            @unlink($tmp);
            throw $e;
        }

        return [$size, hash_final($ctx)];
    }

    public function delete(string $key): void
    {
        $path = $this->safePath($key);
        if (is_file($path)) {
            unlink($path);
        }
    }

    public function openStream(string $key)
    {
        $path = $this->safePath($key);
        if (! is_file($path)) {
            throw new \App\Exceptions\NotFoundError('فایل روی فضای ذخیره‌سازی یافت نشد.');
        }
        $handle = fopen($path, 'rb');
        if ($handle === false) {
            throw new RuntimeException('cannot open stored file');
        }

        return $handle;
    }

    public function assembleChunks(string $targetKey, array $chunkKeys): array
    {
        if ($chunkKeys === []) {
            throw new RuntimeException('no chunks to assemble');
        }
        $target = $this->safePath($targetKey);
        $this->ensureParent($target);
        $tmp = $target.'.tmp';
        $out = fopen($tmp, 'wb');
        if ($out === false) {
            throw new RuntimeException('cannot open assemble temp file');
        }
        $ctx = hash_init('sha256');
        $size = 0;
        try {
            foreach ($chunkKeys as $chunkKey) {
                $source = $this->safePath($chunkKey);
                $in = fopen($source, 'rb');
                if ($in === false) {
                    throw new RuntimeException("missing chunk: {$chunkKey}");
                }
                while (! feof($in)) {
                    $data = fread($in, 1024 * 1024);
                    if ($data === false || $data === '') {
                        continue;
                    }
                    fwrite($out, $data);
                    hash_update($ctx, $data);
                    $size += strlen($data);
                }
                fclose($in);
            }
            fclose($out);
            if ($size <= 0) {
                throw new RuntimeException('no chunks to assemble');
            }
            rename($tmp, $target);
        } catch (\Throwable $e) {
            if (is_resource($out)) {
                fclose($out);
            }
            @unlink($tmp);
            throw $e;
        }

        return [$size, hash_final($ctx)];
    }

    public function checkHealth(): array
    {
        try {
            if (! is_dir($this->root)) {
                mkdir($this->root, 0775, true);
            }
            $probe = $this->root.'/.healthcheck';
            file_put_contents($probe, 'ok');
            unlink($probe);

            return [true, 'ok'];
        } catch (\Throwable $e) {
            return [false, mb_substr($e->getMessage(), 0, 250)];
        }
    }

    public function presignedDownloadUrl(string $key, string $filename): ?string
    {
        return null;
    }

    public function localPath(string $key): ?string
    {
        return $this->safePath($key);
    }

    public function availableBytes(): ?int
    {
        $free = @disk_free_space($this->root);

        return $free === false ? null : (int) $free;
    }

    private function ensureParent(string $path): void
    {
        $dir = dirname($path);
        if (! is_dir($dir)) {
            mkdir($dir, 0775, true);
        }
    }
}
