<?php

namespace App\Services;

use App\Exceptions\NotFoundError;
use App\Exceptions\ValidationAppError;
use App\Models\AuditLog;
use App\Models\Room;
use App\Models\Speaker;
use App\Models\SpeechFile;
use App\Models\User;

/** معادل admin_service.py — آمار و فهرست‌های پنل مدیریت. */
class AdminService
{
    /** @return array<string, int> */
    public static function stats(): array
    {
        return [
            'users_count' => User::query()->count(),
            'rooms_count' => Room::query()->count(),
            'recordings_count' => SpeechFile::query()->where('upload_type', 'recording')->count(),
            'total_storage_bytes' => (int) Room::query()->sum('storage_used_bytes'),
        ];
    }

    /** @return list<array<string, mixed>> */
    public static function listUsers(int $limit = 50, int $offset = 0): array
    {
        $users = User::query()->orderByDesc('id')->offset($offset)->limit($limit)->get();
        $counts = [];
        if ($users->isNotEmpty()) {
            $counts = Room::query()
                ->selectRaw('owner_id, COUNT(*) as aggregate')
                ->whereIn('owner_id', $users->pluck('id'))
                ->groupBy('owner_id')
                ->pluck('aggregate', 'owner_id')
                ->all();
        }
        $results = [];
        foreach ($users as $u) {
            $results[] = [
                'id' => $u->id,
                'username' => $u->username,
                'account_name' => $u->account_name,
                'role' => $u->role,
                'is_active' => $u->is_active,
                'rooms_count' => (int) ($counts[$u->id] ?? 0),
                'storage_used_bytes' => $u->storage_used_bytes,
                'created_at_ms' => $u->created_at_ms,
                'last_login_at_ms' => $u->last_login_at_ms,
            ];
        }

        return $results;
    }

    public static function toggleUserActive(int $targetUserId, User $admin, string $ip = ''): bool
    {
        if ($targetUserId === $admin->id) {
            throw new ValidationAppError('امکان غیرفعال کردن حساب کاربری خودتان وجود ندارد.');
        }
        $user = User::query()->find($targetUserId);
        if (! $user) {
            throw new NotFoundError('کاربر یافت نشد.');
        }
        $user->is_active = ! $user->is_active;
        $user->save();

        AuditLogger::log(
            'admin_toggle_user_active',
            actorUserId: $admin->id,
            actorUsername: $admin->username,
            severity: 'warning',
            targetType: 'user',
            targetId: (string) $user->id,
            detail: ['is_active' => $user->is_active],
            ip: $ip,
        );

        return $user->is_active;
    }

    /** @return list<array<string, mixed>> */
    public static function listRooms(int $limit = 50, int $offset = 0): array
    {
        $rooms = Room::query()->with('owner')->orderByDesc('id')->offset($offset)->limit($limit)->get();
        $counts = [];
        if ($rooms->isNotEmpty()) {
            $counts = Speaker::query()
                ->selectRaw('room_id, COUNT(*) as aggregate')
                ->whereIn('room_id', $rooms->pluck('id'))
                ->groupBy('room_id')
                ->pluck('aggregate', 'room_id')
                ->all();
        }
        $results = [];
        foreach ($rooms as $r) {
            $results[] = [
                'id' => $r->id,
                'owner_id' => $r->owner_id,
                'owner_username' => $r->owner?->username ?? '—',
                'name' => $r->name,
                'capacity' => $r->capacity,
                'speakers_count' => (int) ($counts[$r->id] ?? 0),
                'storage_used_bytes' => $r->storage_used_bytes,
                'created_at_ms' => $r->created_at_ms,
            ];
        }

        return $results;
    }

    /** @return list<AuditLog> */
    public static function listAuditLogs(int $limit = 100, int $offset = 0): array
    {
        return AuditLog::query()->orderByDesc('id')->offset($offset)->limit($limit)->get()->all();
    }
}
