<?php

namespace App\Services\Storage;

use App\Support\Settings;

/** معادل storage/factory.py + امکان ساخت بک‌اند مشخص (برای صف پاک‌سازی B-08). */
class StorageFactory
{
    public function __construct(private readonly Settings $settings)
    {
    }

    public function make(?string $backend = null): StorageBackend
    {
        $name = $backend ?? (string) $this->settings->get('storage_backend', 'local');

        return match ($name) {
            'local' => new LocalStorageBackend($this->settings->resolvedStorageDir()),
            's3' => new S3StorageBackend($this->settings),
            default => throw new \InvalidArgumentException("Unsupported storage backend: {$name}"),
        };
    }

    public function default(): StorageBackend
    {
        return $this->make();
    }
}
