<?php

namespace App\Providers;

use App\Services\Storage\StorageBackend;
use App\Services\Storage\StorageFactory;
use App\Support\Settings;
use Illuminate\Support\ServiceProvider;

class AppServiceProvider extends ServiceProvider
{
    /**
     * بایندینگ‌های اصلی MAS: تنظیمات (از config/mas.php) و بک‌اند ذخیره‌سازی
     * پیش‌فرض به‌صورت singleton ثبت می‌شوند تا در کل درخواست یک نمونه داشته باشیم.
     */
    public function register(): void
    {
        $this->app->singleton(Settings::class, fn () => new Settings(config('mas')));
        $this->app->singleton(
            StorageBackend::class,
            fn ($app) => $app->make(StorageFactory::class)->default(),
        );
    }

    public function boot(): void
    {
        // دیسک s3 لاراول از همان متغیرهای MAS_S3_* نسخهٔ Python تغذیه می‌شود
        // تا S3StorageBackend بدون تنظیم جدا کار کند (endpoint/bucket/کلیدها).
        $mas = (array) config('mas', []);
        if (! empty($mas['s3_bucket'])) {
            config(['filesystems.disks.s3' => [
                'driver' => 's3',
                'key' => (string) ($mas['s3_access_key_id'] ?? ''),
                'secret' => (string) ($mas['s3_secret_access_key'] ?? ''),
                'region' => (string) ($mas['s3_region'] ?? 'us-east-1'),
                'bucket' => (string) $mas['s3_bucket'],
                'url' => ! empty($mas['s3_endpoint_url']) ? (string) $mas['s3_endpoint_url'] : null,
                'endpoint' => ! empty($mas['s3_endpoint_url']) ? (string) $mas['s3_endpoint_url'] : null,
                'use_path_style_endpoint' => ($mas['s3_addressing_style'] ?? 'virtual') === 'path',
                'throw' => false,
            ]]);
        }
    }
}
