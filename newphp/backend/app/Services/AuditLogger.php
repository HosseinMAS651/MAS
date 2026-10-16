<?php

namespace App\Services;

use App\Models\AuditLog;
use App\Support\Mas;

/** ثبت لاگ ممیزی/امنیتی (معادل services/audit.py — رفع SEC-10). */
class AuditLogger
{
    private const SEVERITIES = ['info', 'warning', 'error', 'security'];

    /** @param array<string, mixed>|string $detail */
    public static function log(
        string $action,
        ?int $actorUserId = null,
        string $actorUsername = '',
        string $severity = 'info',
        string $targetType = '',
        string $targetId = '',
        array|string $detail = '',
        string $ip = '',
        string $userAgent = '',
    ): AuditLog {
        $detailStr = is_string($detail)
            ? $detail
            : json_encode($detail, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);

        return AuditLog::create([
            'actor_user_id' => $actorUserId,
            'actor_username' => mb_substr($actorUsername, 0, 32),
            'action' => mb_substr($action, 0, 48),
            'severity' => in_array($severity, self::SEVERITIES, true) ? $severity : 'info',
            'target_type' => mb_substr($targetType, 0, 32),
            'target_id' => mb_substr((string) $targetId, 0, 64),
            'detail' => $detailStr === false ? '' : $detailStr,
            'ip' => mb_substr($ip, 0, 64),
            'user_agent' => mb_substr($userAgent, 0, 255),
            'created_at_ms' => Mas::nowMs(),
        ]);
    }
}
