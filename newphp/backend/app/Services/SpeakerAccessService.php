<?php

namespace App\Services;

use App\Models\Room;
use App\Models\Speaker;
use App\Support\Mas;
use Illuminate\Support\Facades\DB;

/** معادل speaker_access_service.py — ورود با کد ۴کاراکتری و حضور دستگاه سخنران. */
class SpeakerAccessService
{
    public const PRESENCE_TIMEOUT_MS = 60000;

    public function __construct(private readonly SecurityService $security)
    {
    }

    public static function normalizeCode(string $code): string
    {
        return strtoupper(trim($code));
    }

    /** @return array{0: Speaker, 1: string}|null (سخنران، توکن خام نشست دستگاه) */
    public function enter(Room $roomParam, string $code): ?array
    {
        return DB::transaction(function () use ($roomParam, $code) {
            $room = Room::query()->where('id', $roomParam->id)->lockForUpdate()->first();
            if (! $room || ! $room->speaker_mode_enabled) {
                return null;
            }
            $normalized = self::normalizeCode($code);
            if (strlen($normalized) !== 4) {
                return null;
            }
            $hash = $this->security->hashToken("speaker-code:{$room->id}:{$normalized}");
            $speaker = Speaker::query()
                ->where('room_id', $room->id)
                ->where('speaker_code_hash', $hash)
                ->lockForUpdate()
                ->first();
            if (! $speaker) {
                return null;
            }
            $rawToken = $this->security->generateSessionToken();
            $speaker->speaker_session_hash = $this->security->hashToken("speaker-session:{$rawToken}");
            $speaker->presence_status = 'connected';
            $speaker->presence_last_seen_at_ms = Mas::nowMs();
            $speaker->updated_at_ms = $speaker->presence_last_seen_at_ms;
            $speaker->save();

            return [$speaker, $rawToken];
        });
    }

    public function authenticate(Room $roomParam, string $rawToken): ?Speaker
    {
        return DB::transaction(function () use ($roomParam, $rawToken) {
            $room = Room::query()->where('id', $roomParam->id)->lockForUpdate()->first();
            if (! $room || ! $room->speaker_mode_enabled || $rawToken === '') {
                return null;
            }
            $digest = $this->security->hashToken("speaker-session:{$rawToken}");
            $speaker = Speaker::query()
                ->where('room_id', $room->id)
                ->where('speaker_session_hash', $digest)
                ->lockForUpdate()
                ->first();
            if (! $speaker) {
                return null;
            }
            $now = Mas::nowMs();
            if ($now - $speaker->presence_last_seen_at_ms >= self::PRESENCE_TIMEOUT_MS) {
                $speaker->speaker_session_hash = null;
                $speaker->presence_status = 'offline';
                $speaker->updated_at_ms = $now;
                $speaker->save();

                return null;
            }

            return $speaker;
        });
    }

    public function heartbeat(Speaker $speaker, bool $microphoneReady): string
    {
        $now = Mas::nowMs();
        $speaker->presence_status = $microphoneReady ? 'ready' : 'connected';
        $speaker->presence_last_seen_at_ms = $now;
        $speaker->updated_at_ms = $now;
        $speaker->save();

        return $speaker->presence_status;
    }

    public function leave(Speaker $speaker): void
    {
        $speaker->speaker_session_hash = null;
        $speaker->presence_status = 'offline';
        $speaker->updated_at_ms = Mas::nowMs();
        $speaker->save();
    }
}
