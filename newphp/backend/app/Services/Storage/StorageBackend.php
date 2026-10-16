<?php

namespace App\Services\Storage;

/**
 * قرارداد بک‌اند ذخیره‌سازی (معادل storage/base.py).
 * همهٔ متدها [size_bytes, sha256_hex] یا مسیر/استریم برمی‌گردانند.
 */
interface StorageBackend
{
    /** @return array{0: int, 1: string} */
    public function saveBytes(string $key, string $data): array;

    /**
     * ذخیرهٔ جریانی از روی فایل آپلودشده بدون بارگذاری کامل در حافظه.
     * وقتی $limitBytes داده شود، به‌محض عبور حجم از سقف، نوشتن متوقف و
     * خروجی ناقص پاک می‌شود (سقف سخت معادل _LimitedStream نسخهٔ Python).
     *
     * @param  resource  $stream
     * @return array{0: int, 1: string}
     */
    public function saveStream(string $key, $stream, ?int $limitBytes = null): array;

    public function delete(string $key): void;

    /**
     * استریم خواندن شیء (برای سرو Range روی بک‌اند غیرمحلی).
     *
     * @return resource
     */
    public function openStream(string $key);

    /** @return array{0: int, 1: string} مونتاژ ترتیبی تکه‌ها در کلید مقصد */
    public function assembleChunks(string $targetKey, array $chunkKeys): array;

    /** @return array{0: bool, 1: string} */
    public function checkHealth(): array;

    /** URL دانلود مستقیم امضاشده (فقط بک‌اند ابری؛ محلی null). */
    public function presignedDownloadUrl(string $key, string $filename): ?string;

    /** مسیر فیزیکی امن وقتی بک‌اند محلی است؛ وگرنه null. */
    public function localPath(string $key): ?string;

    /** بایت آزاد قابل اندازه‌گیری؛ null یعنی نامشخص. */
    public function availableBytes(): ?int;
}
