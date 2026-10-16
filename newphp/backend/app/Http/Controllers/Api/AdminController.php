<?php

namespace App\Http\Controllers\Api;

use App\Exceptions\ValidationAppError;
use App\Http\Controllers\Controller;
use App\Models\AuditLog;
use App\Presenters\MasPresenter;
use App\Services\AdminService;
use App\Services\SecurityService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

/** معادل mas_app/api/routers/admin.py. */
class AdminController extends Controller
{
    public function __construct(
        private readonly SecurityService $security,
    ) {
    }

    /** @return array{0: int, 1: int} (limit, offset) با همان کران‌های Query در FastAPI */
    private function pagination(Request $request, int $defaultLimit, int $maxLimit): array
    {
        $limit = (int) $request->query('limit', $defaultLimit);
        $offset = (int) $request->query('offset', 0);
        if ($limit < 1 || $limit > $maxLimit || $offset < 0) {
            throw new ValidationAppError('پارامترهای صفحه‌بندی نامعتبر است.');
        }

        return [$limit, $offset];
    }

    public function stats(): JsonResponse
    {
        return response()->json(['ok' => true, 'stats' => AdminService::stats()]);
    }

    public function users(Request $request): JsonResponse
    {
        [$limit, $offset] = $this->pagination($request, 50, 200);

        return response()->json(['ok' => true, 'users' => AdminService::listUsers($limit, $offset)]);
    }

    public function rooms(Request $request): JsonResponse
    {
        [$limit, $offset] = $this->pagination($request, 50, 200);

        return response()->json(['ok' => true, 'rooms' => AdminService::listRooms($limit, $offset)]);
    }

    public function auditLogs(Request $request): JsonResponse
    {
        [$limit, $offset] = $this->pagination($request, 100, 500);
        $logs = array_map(
            fn (AuditLog $log) => MasPresenter::auditLog($log),
            AdminService::listAuditLogs($limit, $offset),
        );

        return response()->json(['ok' => true, 'logs' => $logs]);
    }

    public function toggleUserActive(Request $request, int $userId): JsonResponse
    {
        $admin = $request->attributes->get('mas_user');
        $isActive = AdminService::toggleUserActive(
            $userId,
            $admin,
            $this->security->extractClientIp($request),
        );

        return response()->json([
            'ok' => true,
            'is_active' => $isActive,
            'message' => 'وضعیت کاربر به‌روزرسانی شد.',
        ]);
    }
}
