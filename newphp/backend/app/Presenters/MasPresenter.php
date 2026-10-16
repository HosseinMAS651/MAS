<?php

namespace App\Presenters;

use App\Models\AuditLog;
use App\Models\Room;
use App\Models\Speaker;
use App\Models\SpeechFile;
use App\Models\User;
use App\Services\RoomService;

/**
 * ساخت آرایه‌های پاسخ API با همان نام/نوع فیلدهای اسکیماهای Pydantic نسخهٔ
 * Python تا فرانت‌اند React بدون هیچ تغییری با این بک‌اند کار کند.
 */
class MasPresenter
{
    /** @return array<string, mixed> معادل UserResponse */
    public static function user(User $user): array
    {
        return [
            'id' => $user->id,
            'username' => $user->username,
            'account_name' => $user->account_name,
            'age' => $user->age,
            'job' => $user->job,
            'role' => $user->role,
            'is_active' => $user->is_active,
            'timezone' => $user->timezone,
            'calendar' => $user->calendar,
            'storage_used_bytes' => $user->storage_used_bytes,
            'created_at_ms' => $user->created_at_ms,
            'has_recovery_code' => ! empty($user->recovery_code_hash),
        ];
    }

    /** @return array<string, mixed> معادل FileResponse */
    public static function file(SpeechFile $file): array
    {
        return [
            'id' => $file->id,
            'room_id' => $file->room_id,
            'speaker_id' => $file->speaker_id,
            'filename' => $file->filename,
            'content_type' => $file->content_type,
            'size_bytes' => $file->size_bytes,
            'upload_type' => $file->upload_type,
            'approval_status' => $file->approval_status,
            'duration_ms' => $file->duration_ms,
            'speaker_name' => $file->speaker_name,
            'created_at_ms' => $file->created_at_ms,
        ];
    }

    /** فایل عمومی: content_type از روی پسوند بازنویسی می‌شود (مثل نسخهٔ Python). */
    public static function publicFile(SpeechFile $file): array
    {
        $data = self::file($file);
        $data['content_type'] = self::publicContentType($file);

        return $data;
    }

    public static function publicContentType(SpeechFile $file): string
    {
        $dot = strrpos($file->filename, '.');
        $ext = $dot === false ? '' : strtolower(substr($file->filename, $dot));

        return RoomService::SAFE_MIME_BY_EXTENSION[$ext] ?? 'application/octet-stream';
    }

    /** @return array<string, mixed> معادل SpeakerResponse */
    public static function speaker(Speaker $speaker, ?int $elapsedMs = null, ?int $overtimeMs = null): array
    {
        $timer = $speaker->timer;

        return [
            'id' => $speaker->id,
            'room_id' => $speaker->room_id,
            'order_index' => $speaker->order_index,
            'name' => $speaker->name,
            'gender' => $speaker->gender,
            'age' => $speaker->age,
            'description' => $speaker->description,
            'speaking_seconds' => $speaker->speaking_seconds,
            'is_finished' => $speaker->is_finished,
            'finished_at_ms' => $speaker->finished_at_ms,
            'elapsed_ms' => $elapsedMs ?? ($timer?->elapsed_ms ?? 0),
            'overtime_ms' => $overtimeMs ?? ($timer?->overtime_ms ?? 0),
        ];
    }

    /** @return array<string, mixed> معادل OwnerSpeakerResponse */
    public static function ownerSpeaker(
        Speaker $speaker,
        ?string $speakerCode,
        ?int $elapsedMs = null,
        ?int $overtimeMs = null,
    ): array {
        $data = self::speaker($speaker, $elapsedMs, $overtimeMs);
        $data['speaker_code'] = $speakerCode;
        $data['presence_status'] = $speaker->presence_status;
        $data['presence_last_seen_at_ms'] = $speaker->presence_last_seen_at_ms;

        return $data;
    }

    /** @return array<string, mixed> معادل RoomSummaryResponse */
    public static function roomSummary(Room $room): array
    {
        $speakers = $room->speakers;
        $active = 0;
        foreach ($speakers as $s) {
            if (trim($s->name) !== '') {
                $active++;
            }
        }

        return [
            'id' => $room->id,
            'name' => $room->name,
            'description' => $room->description,
            'capacity' => $room->capacity,
            'recording_enabled' => $room->recording_enabled,
            'live_files_enabled' => $room->live_files_enabled,
            'speaker_mode_enabled' => $room->speaker_mode_enabled,
            'speaker_uploads_enabled' => $room->speaker_uploads_enabled,
            'public_enabled' => $room->public_enabled,
            'timing_mode' => $room->timing_mode,
            'global_seconds' => $room->global_seconds,
            'order_mode' => $room->order_mode,
            'storage_used_bytes' => $room->storage_used_bytes,
            'created_at_ms' => $room->created_at_ms,
            'speaker_count' => $speakers->count(),
            'active_speaker_count' => $active,
        ];
    }

    /**
     * @param  array<string, mixed>  $snapshot  خروجی TimerService::getSnapshot
     * @return array<string, mixed> معادل TimerStateResponse
     */
    public static function timerState(Room $room, array $snapshot): array
    {
        $speakers = [];
        foreach ($snapshot['speakers'] as $s) {
            $speakers[] = self::speaker($s);
        }

        $current = $snapshot['current_speaker'];
        $currentData = $current
            ? self::speaker($current, $snapshot['elapsed_ms'], $snapshot['overtime_ms'])
            : null;

        $liveFiles = [];
        if ($room->live_files_enabled) {
            $currentId = $snapshot['current_speaker_id'];
            foreach ($room->files as $f) {
                if ($f->upload_type === 'common'
                    || ($f->upload_type === 'speaker' && $currentId !== null && $f->speaker_id === $currentId)) {
                    $liveFiles[] = self::file($f);
                }
            }
        }

        return [
            'room_id' => $room->id,
            'version' => $snapshot['version'],
            'running' => $snapshot['running'],
            'awaiting_decision' => $snapshot['awaiting_decision'],
            'stop_reason' => $snapshot['stop_reason'],
            'current_index' => $snapshot['current_index'],
            'current_speaker_id' => $snapshot['current_speaker_id'],
            'current_speaker' => $currentData,
            'elapsed_ms' => $snapshot['elapsed_ms'],
            'remaining_ms' => $snapshot['remaining_ms'],
            'overtime_ms' => $snapshot['overtime_ms'],
            'limit_ms' => $snapshot['limit_ms'],
            'total_speakers' => $snapshot['total_speakers'],
            'finished_speakers' => $snapshot['finished_speakers'],
            'speakers' => $speakers,
            'live_files' => $liveFiles,
            'recording_status' => $snapshot['recording_status'],
        ];
    }

    /**
     * @param  array<string, mixed>  $snapshot
     * @return array<string, mixed> معادل PublicRoomStateResponse
     */
    public static function publicState(Room $room, array $snapshot): array
    {
        $speakers = [];
        foreach ($snapshot['speakers'] as $s) {
            $speakers[] = self::speaker($s);
        }
        $current = $snapshot['current_speaker'];

        $liveFiles = [];
        if ($room->live_files_enabled) {
            $currentId = $snapshot['current_speaker_id'];
            foreach ($room->files as $f) {
                if ($f->approval_status !== 'approved') {
                    continue;
                }
                if ($f->upload_type === 'common'
                    || ($f->upload_type === 'speaker' && $currentId !== null && $f->speaker_id === $currentId)) {
                    $liveFiles[] = self::publicFile($f);
                }
            }
        }

        return [
            'room_name' => $room->name,
            'public_enabled' => $room->public_enabled,
            'speaker_mode_enabled' => $room->speaker_mode_enabled,
            'speaker_uploads_enabled' => $room->speaker_uploads_enabled,
            'running' => $snapshot['running'],
            'awaiting_decision' => $snapshot['awaiting_decision'],
            'current_index' => $snapshot['current_index'],
            'current_speaker' => $current
                ? self::speaker($current, $snapshot['elapsed_ms'], $snapshot['overtime_ms'])
                : null,
            'elapsed_ms' => $snapshot['elapsed_ms'],
            'remaining_ms' => $snapshot['remaining_ms'],
            'overtime_ms' => $snapshot['overtime_ms'],
            'limit_ms' => $snapshot['limit_ms'],
            'total_speakers' => $snapshot['total_speakers'],
            'finished_speakers' => $snapshot['finished_speakers'],
            'speakers' => $speakers,
            'live_files' => $liveFiles,
        ];
    }

    /** @return array<string, mixed> معادل AuditLogItem */
    public static function auditLog(AuditLog $log): array
    {
        return [
            'id' => $log->id,
            'actor_username' => $log->actor_username,
            'action' => $log->action,
            'severity' => $log->severity,
            'target_type' => $log->target_type,
            'target_id' => $log->target_id,
            'detail' => $log->detail,
            'ip' => $log->ip,
            'created_at_ms' => $log->created_at_ms,
        ];
    }
}
