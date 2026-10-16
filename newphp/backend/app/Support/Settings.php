<?php

namespace App\Support;

use RuntimeException;

/**
 * معادل mas_app.config.Settings در نسخهٔ Python: مقادیر خام از config/mas.php
 * خوانده می‌شوند و مقادیر مشتق‌شده + اعتبارسنجی‌های زمان اجرا این‌جا متمرکز است.
 */
class Settings
{
    /** @var array<string, mixed> */
    private array $values;

    /** @param array<string, mixed> $values */
    public function __construct(array $values)
    {
        $this->values = $values;
        $this->validate();
    }

    public static function fromConfig(): self
    {
        return new self(config('mas'));
    }

    public function get(string $key, mixed $default = null): mixed
    {
        return $this->values[$key] ?? $default;
    }

    public function isProduction(): bool
    {
        return $this->values['env'] === 'production';
    }

    public function secretKey(): string
    {
        return (string) $this->values['secret_key'];
    }

    public function maxUploadBytes(): int
    {
        return (int) $this->values['max_upload_mb'] * 1024 * 1024;
    }

    public function maxRoomStorageBytes(): int
    {
        return (int) $this->values['max_room_storage_mb'] * 1024 * 1024;
    }

    public function maxUserStorageBytes(): int
    {
        return (int) $this->values['max_user_storage_mb'] * 1024 * 1024;
    }

    public function maxRecordingSeconds(): int
    {
        return (int) $this->values['max_recording_minutes'] * 60;
    }

    /** سقف تقریبی بایت برای یک ضبط، بر اساس بیت‌ریت و سقف مدت. */
    public function maxRecordingBytes(): int
    {
        return (int) ((int) $this->values['recording_bitrate_kbps'] * 1000 / 8 * $this->maxRecordingSeconds()) + 65536;
    }

    public function maxRecordingChunkBytes(): int
    {
        return (int) $this->values['max_recording_chunk_mb'] * 1024 * 1024;
    }

    /** @return list<string> پسوندهای مجاز آپلود (با نقطه، حروف کوچک) */
    public function allowedExtensions(): array
    {
        $parts = explode(',', (string) $this->values['allowed_upload_extensions']);
        $clean = [];
        foreach ($parts as $part) {
            $ext = strtolower(trim($part));
            if ($ext === '') {
                continue;
            }
            $clean[] = str_starts_with($ext, '.') ? $ext : '.'.$ext;
        }

        return array_values(array_unique($clean));
    }

    /** مسیر ریشهٔ ذخیره‌سازی محلی (نسبی‌ها نسبت به ریشهٔ بک‌اند حل می‌شوند). */
    public function resolvedStorageDir(): string
    {
        $path = (string) $this->values['storage_dir'];
        if ($path === '' || $path[0] === '/' || preg_match('/^[A-Za-z]:[\\\\\/]/', $path)) {
            return $path;
        }

        return base_path($path);
    }

    public function sessionIdleSeconds(): int
    {
        return (int) $this->values['session_idle_minutes'] * 60;
    }

    public function sessionAbsoluteSeconds(): int
    {
        return (int) $this->values['session_absolute_days'] * 86400;
    }

    public function recordingAbandonSeconds(): int
    {
        return (int) $this->values['recording_abandon_minutes'] * 60;
    }

    public function docsEnabled(): bool
    {
        $flag = $this->values['enable_docs'] ?? null;

        return $flag === null ? ! $this->isProduction() : filter_var($flag, FILTER_VALIDATE_BOOL);
    }

    /** اعتبارسنجی‌های حیاتی زمان اجرا؛ در production ناامن یعنی توقف روشن، نه اجرای بی‌صدا. */
    private function validate(): void
    {
        $secret = (string) ($this->values['secret_key'] ?? '');
        if ($secret === '') {
            if ($this->isProduction()) {
                throw new RuntimeException(
                    "MAS_SECRET_KEY در production اجباری است. یک مقدار تصادفی بسازید:\n"
                    .'    php -r "echo bin2hex(random_bytes(32));"'
                );
            }
            // فقط توسعه/تست: کلید موقت از APP_KEY مشتق می‌شود تا نشست‌ها بین ریکوئست‌ها پایدار بمانند.
            $this->values['secret_key'] = hash('sha256', 'mas-dev-secret:'.config('app.key', 'mas'));
        } elseif (strlen($secret) < 32 && $this->values['env'] !== 'test') {
            throw new RuntimeException('MAS_SECRET_KEY باید حداقل ۳۲ کاراکتر باشد.');
        }

        if ((int) $this->values['min_room_capacity'] > (int) $this->values['max_room_capacity']) {
            throw new RuntimeException('MAS_MIN_ROOM_CAPACITY نمی‌تواند از MAS_MAX_ROOM_CAPACITY بزرگ‌تر باشد.');
        }
        if ((int) $this->values['max_room_storage_mb'] < (int) $this->values['max_upload_mb']) {
            throw new RuntimeException('MAS_MAX_ROOM_STORAGE_MB باید حداقل به اندازهٔ MAS_MAX_UPLOAD_MB باشد.');
        }
        if ($this->values['storage_backend'] === 's3') {
            $missing = [];
            foreach (['s3_bucket' => 'MAS_S3_BUCKET', 's3_access_key_id' => 'MAS_S3_ACCESS_KEY_ID',
                's3_secret_access_key' => 'MAS_S3_SECRET_ACCESS_KEY', 's3_region' => 'MAS_S3_REGION'] as $key => $envName) {
                if (empty($this->values[$key])) {
                    $missing[] = $envName;
                }
            }
            if ($missing !== []) {
                throw new RuntimeException(
                    'MAS_STORAGE_BACKEND=s3 است ولی این متغیرها تنظیم نشده‌اند: '.implode(', ', $missing)
                );
            }
        }
        if ($this->values['cookie_samesite'] === 'none' && ! $this->values['cookie_secure']) {
            throw new RuntimeException('MAS_COOKIE_SAMESITE=none فقط همراه MAS_COOKIE_SECURE فعال مجاز است.');
        }
    }
}
