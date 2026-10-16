<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Services\Storage\StorageFactory;
use App\Support\Settings;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\DB;

/** معادل mas_app/api/routers/health.py. */
class HealthController extends Controller
{
    public function health(): JsonResponse
    {
        return response()->json(['ok' => true, 'version' => '2.0.0']);
    }

    public function ready(StorageFactory $factory, Settings $settings): JsonResponse
    {
        [$dbOk, $dbError] = $this->checkDatabase();
        [$storageOk, $storageMessage] = $factory->make()->checkHealth();
        $ready = $dbOk && $storageOk;

        return response()->json([
            'ok' => $ready,
            'version' => '2.0.0',
            'db' => $dbOk,
            'db_error' => $dbOk ? null : $dbError,
            'storage' => $storageOk,
            'storage_error' => $storageOk ? null : $storageMessage,
            'storage_backend' => (string) $settings->get('storage_backend'),
        ], $ready ? 200 : 503);
    }

    /** @return array{0: bool, 1: ?string} */
    private function checkDatabase(): array
    {
        try {
            DB::connection()->getPdo();
            DB::select('SELECT 1');

            return [true, null];
        } catch (\Throwable $e) {
            return [false, mb_substr($e->getMessage(), 0, 250)];
        }
    }
}
