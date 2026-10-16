<?php

namespace App\Console\Commands;

use App\Services\CleanupService;
use App\Support\Settings;
use Illuminate\Console\Command;

/** یک چرخهٔ نگهداری: پردازش صف پاک‌سازی + جمع‌آوری ضبط‌های متروکه. */
class MaintenanceCommand extends Command
{
    protected $signature = 'mas:maintenance';

    protected $description = 'پردازش صف پاک‌سازی فایل‌ها و ضبط‌های متروکه (معادل ورکر پس‌زمینهٔ نسخهٔ Python)';

    public function handle(CleanupService $cleanup, Settings $settings): int
    {
        if (! $settings->get('maintenance_enabled')) {
            $this->info('نگهداری دوره‌ای غیرفعال است (MAS_MAINTENANCE_ENABLED=false).');

            return self::SUCCESS;
        }

        $deleted = $cleanup->processQueue((int) $settings->get('cleanup_queue_batch', 25));
        $recovered = $cleanup->cleanAbandonedRecordings();
        $this->info("چرخهٔ نگهداری تمام شد: {$deleted} فایل از صف پاک شد، {$recovered} ضبط متروکه جمع‌آوری شد.");

        return self::SUCCESS;
    }
}
