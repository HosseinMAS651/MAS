<?php

namespace App\Services;

use App\Models\CleanupQueue;
use App\Models\RecordingSession;
use App\Services\Storage\StorageBackend;
use App\Services\Storage\StorageFactory;
use App\Support\Mas;
use App\Support\Settings;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Log;

/** معادل cleanup_service.py — پردازش صف حذف فیزیکی و ضبط‌های متروکه. */
class CleanupService
{
    public function __construct(
        private readonly Settings $settings,
        private readonly StorageBackend $storage,
        private readonly StorageFactory $storageFactory,
    ) {
    }

    public function processQueue(int $limit = 50): int
    {
        $now = Mas::nowMs();
        $deleted = 0;

        $items = DB::transaction(function () use ($now, $limit) {
            return CleanupQueue::query()
                ->where('next_attempt_at_ms', '<=', $now)
                ->orderBy('id')
                ->limit($limit)
                ->lockForUpdate()
                ->get()
                ->all();
        });

        foreach ($items as $item) {
            try {
                // هر آیتم با بک‌اند ثبت‌شدهٔ خودش حذف می‌شود (رفع B-08 نسخهٔ Python:
                // آن‌جا backend ذخیره‌شدهٔ آیتم نادیده گرفته می‌شد).
                $backend = $item->backend === (string) $this->settings->get('storage_backend')
                    ? $this->storage
                    : $this->storageFactory->make($item->backend);
                $backend->delete($item->storage_key);
                $item->delete();
                $deleted++;
            } catch (\Throwable $e) {
                $item->attempts += 1;
                $item->last_error = mb_substr($e->getMessage(), 0, 250);
                $delaySec = min(3600, (2 ** $item->attempts) * 10); // backoff تصاعدی
                $item->next_attempt_at_ms = $now + $delaySec * 1000;
                $item->save();
                Log::warning("خطا در حذف فایل {$item->storage_key}: {$e->getMessage()}");
            }
        }

        return $deleted;
    }

    public function cleanAbandonedRecordings(): int
    {
        $threshold = Mas::nowMs() - $this->settings->recordingAbandonSeconds() * 1000;

        return DB::transaction(function () use ($threshold) {
            $abandoned = RecordingSession::query()
                ->whereIn('status', ['recording', 'paused'])
                ->where('last_chunk_at_ms', '<', $threshold)
                ->lockForUpdate()
                ->get();
            $count = 0;
            foreach ($abandoned as $rec) {
                foreach ($rec->chunks()->get() as $c) {
                    CleanupQueue::enqueue($c->backend, $c->storage_key, 'abandoned_recording');
                }
                $rec->status = 'discarded';
                $rec->error = 'به دلیل قطع ارتباط و عدم دریافت داده جدید متوقف شد.';
                $rec->ended_at_ms = Mas::nowMs();
                $rec->active_since_ms = 0;
                $rec->version += 1;
                $rec->save();
                $count++;
            }

            return $count;
        });
    }
}
