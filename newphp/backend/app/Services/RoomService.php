<?php

namespace App\Services;

use App\Exceptions\AppError;
use App\Exceptions\FileUploadError;
use App\Exceptions\NotFoundError;
use App\Exceptions\QuotaExceededError;
use App\Exceptions\ValidationAppError;
use App\Models\CleanupQueue;
use App\Models\RecordingChunk;
use App\Models\RecordingSession;
use App\Models\Room;
use App\Models\RoomState;
use App\Models\Speaker;
use App\Models\SpeakerTimerState;
use App\Models\SpeechFile;
use App\Models\User;
use App\Services\Storage\StorageBackend;
use App\Support\Mas;
use App\Support\Settings;
use Illuminate\Support\Facades\DB;
use SimpleSoftwareIO\QrCode\Facades\QrCode;

/**
 * معادل mas_app/services/room_service.py — مدیریت اتاق، ظرفیت، فایل‌ها،
 * کد سخنران، توکن عمومی و سهمیه‌های ذخیره‌سازی.
 */
class RoomService
{
    private const SPEAKER_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';

    /** نگاشت پسوند به MIME امن؛ نوع محتوا هرگز از هدر multipart گرفته نمی‌شود. */
    public const SAFE_MIME_BY_EXTENSION = [
        '.pdf' => 'application/pdf',
        '.txt' => 'text/plain; charset=utf-8',
        '.md' => 'text/markdown; charset=utf-8',
        '.csv' => 'text/csv; charset=utf-8',
        '.rtf' => 'application/rtf',
        '.doc' => 'application/msword',
        '.docx' => 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.odt' => 'application/vnd.oasis.opendocument.text',
        '.ppt' => 'application/vnd.ms-powerpoint',
        '.pptx' => 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        '.odp' => 'application/vnd.oasis.opendocument.presentation',
        '.xls' => 'application/vnd.ms-excel',
        '.xlsx' => 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.ods' => 'application/vnd.oasis.opendocument.spreadsheet',
        '.png' => 'image/png',
        '.jpg' => 'image/jpeg',
        '.jpeg' => 'image/jpeg',
        '.gif' => 'image/gif',
        '.webp' => 'image/webp',
        '.bmp' => 'image/bmp',
        '.tiff' => 'image/tiff',
        '.mp3' => 'audio/mpeg',
        '.m4a' => 'audio/mp4',
        '.aac' => 'audio/aac',
        '.ogg' => 'audio/ogg',
        '.oga' => 'audio/ogg',
        '.opus' => 'audio/ogg',
        '.wav' => 'audio/wav',
        '.flac' => 'audio/flac',
        '.weba' => 'audio/webm',
        '.mp4' => 'video/mp4',
        '.m4v' => 'video/mp4',
        '.webm' => 'video/webm',
        '.ogv' => 'video/ogg',
        '.mov' => 'video/quicktime',
        '.avi' => 'video/x-msvideo',
        '.mkv' => 'video/x-matroska',
    ];

    public function __construct(
        public readonly Settings $settings,
        private readonly StorageBackend $storage,
        private readonly SecurityService $security,
    ) {
    }

    public function storage(): StorageBackend
    {
        return $this->storage;
    }

    // ── مرتب‌سازی خودکار (alpha/age) ──────────────────────────
    public static function applyRoomSpeakerOrder(Room $room): void
    {
        if (! in_array($room->order_mode, ['alpha', 'age'], true)) {
            return;
        }
        $speakers = $room->speakers()->get()->all();
        if (count($speakers) <= 1) {
            return;
        }
        if ($room->order_mode === 'alpha') {
            usort($speakers, function (Speaker $a, Speaker $b) {
                $ka = [trim($a->name) === '' ? 1 : 0, mb_strtolower(trim($a->name)), $a->id];
                $kb = [trim($b->name) === '' ? 1 : 0, mb_strtolower(trim($b->name)), $b->id];

                return $ka <=> $kb;
            });
        } else { // age: بزرگ‌تر به کوچک‌تر
            usort($speakers, function (Speaker $a, Speaker $b) {
                $ka = [$a->age === null ? 1 : 0, -($a->age ?? 0), mb_strtolower(trim($a->name)), $a->id];
                $kb = [$b->age === null ? 1 : 0, -($b->age ?? 0), mb_strtolower(trim($b->name)), $b->id];

                return $ka <=> $kb;
            });
        }
        // دو مرحله‌ای برای نقض‌نکردن یکتایی (room_id, order_index)
        foreach ($speakers as $idx => $sp) {
            $sp->order_index = 100000 + $idx;
            $sp->save();
        }
        foreach ($speakers as $idx => $sp) {
            $sp->order_index = $idx;
            $sp->save();
        }
    }

    // ── کد سخنران ─────────────────────────────────────────────
    public function ensureSpeakerCode(Room $room, Speaker $speaker): string
    {
        if ($speaker->speaker_code_hash && $speaker->speaker_code_encrypted) {
            return $this->security->decryptSecret($speaker->speaker_code_encrypted);
        }
        $existing = Speaker::query()
            ->where('room_id', $room->id)
            ->whereNotNull('speaker_code_hash')
            ->where('id', '!=', $speaker->id)
            ->pluck('speaker_code_hash')
            ->all();
        $existingSet = array_flip($existing);

        for ($attempt = 0; $attempt < 100; $attempt++) {
            $code = '';
            for ($i = 0; $i < 4; $i++) {
                $code .= self::SPEAKER_CODE_ALPHABET[random_int(0, strlen(self::SPEAKER_CODE_ALPHABET) - 1)];
            }
            $digest = $this->security->hashToken("speaker-code:{$room->id}:{$code}");
            if (! isset($existingSet[$digest])) {
                $speaker->speaker_code_hash = $digest;
                $speaker->speaker_code_encrypted = $this->security->encryptSecret($code);
                $speaker->save();

                return $code;
            }
        }
        throw new \RuntimeException('Unable to generate a unique speaker access code for this room.');
    }

    public function rotateSpeakerCode(Room $room, int $speakerId): string
    {
        return DB::transaction(function () use ($room, $speakerId) {
            $room = $this->lockRoom($room->id);
            $speaker = Speaker::query()
                ->where('id', $speakerId)->where('room_id', $room->id)
                ->lockForUpdate()->first();
            if (! $speaker) {
                throw new NotFoundError('سخنران مورد نظر یافت نشد.');
            }
            $active = RecordingSession::query()
                ->where('room_id', $room->id)
                ->where('speaker_id', $speaker->id)
                ->whereIn('status', ['recording', 'paused', 'finalizing'])
                ->exists();
            if ($active) {
                throw new AppError(
                    'تا پایان یا ذخیرهٔ ضبط فعال این سخنران، کد را نمی‌توان تعویض کرد.',
                    code: 'ACTIVE_RECORDING_BLOCKS_CODE_ROTATION',
                    statusCode: 409,
                );
            }
            $speaker->speaker_code_hash = null;
            $speaker->speaker_code_encrypted = null;
            $speaker->speaker_session_hash = null;
            $speaker->presence_status = 'offline';
            $speaker->presence_last_seen_at_ms = 0;
            $code = $this->ensureSpeakerCode($room, $speaker);
            $speaker->updated_at_ms = Mas::nowMs();
            $speaker->save();

            return $code;
        });
    }

    public function speakerCodeForOwner(Speaker $speaker): ?string
    {
        if (! $speaker->speaker_code_encrypted) {
            return null;
        }

        return $this->security->decryptSecret($speaker->speaker_code_encrypted);
    }

    public function expireSpeakerPresence(Room $room): void
    {
        $cutoff = Mas::nowMs() - 60000;
        $changed = false;
        foreach ($room->speakers as $speaker) {
            if ($speaker->speaker_session_hash && $speaker->presence_last_seen_at_ms <= $cutoff) {
                $speaker->speaker_session_hash = null;
                $speaker->presence_status = 'offline';
                $speaker->save();
                $changed = true;
            }
        }
    }

    // ── اعتبارسنجی ────────────────────────────────────────────
    public function validateRoomText(string $name, string $description): void
    {
        // رفع B-06: نام فقط‌فاصله در هر دو لایه (اسکیما و سرویس) رد می‌شود.
        if (trim($name) === '') {
            throw new ValidationAppError('نام اتاق نمی‌تواند خالی باشد.');
        }
        if (mb_strlen(trim($name)) > (int) $this->settings->get('max_room_name_length')) {
            throw new ValidationAppError(
                'نام اتاق نمی‌تواند بیش از '.$this->settings->get('max_room_name_length').' نویسه باشد.'
            );
        }
        if (mb_strlen($description) > (int) $this->settings->get('max_description_length')) {
            throw new ValidationAppError(
                'توضیحات نمی‌تواند بیش از '.$this->settings->get('max_description_length').' نویسه باشد.'
            );
        }
    }

    /** رفع B-05: ظرفیت خارج از بازه با خطای صریح رد می‌شود، نه clamp ساکت. */
    public function validateCapacity(int $capacity): int
    {
        $min = (int) $this->settings->get('min_room_capacity');
        $max = (int) $this->settings->get('max_room_capacity');
        if ($capacity < $min || $capacity > $max) {
            throw new ValidationAppError("ظرفیت اتاق باید بین {$min} تا {$max} نفر باشد.");
        }

        return $capacity;
    }

    // ── قفل و دسترسی ──────────────────────────────────────────
    public function lockRoom(int $roomId): Room
    {
        $room = Room::query()->where('id', $roomId)->lockForUpdate()->first();
        if (! $room) {
            throw new NotFoundError('اتاق مورد نظر یافت نشد.');
        }

        return $room;
    }

    private function lockOwner(int $ownerId): ?User
    {
        return User::query()->where('id', $ownerId)->lockForUpdate()->first();
    }

    /** @return list<Room> */
    public function listRoomsForUser(int $userId): array
    {
        return Room::query()->where('owner_id', $userId)->orderByDesc('id')->get()->all();
    }

    public function getRoomForUser(int $roomId, User $user): Room
    {
        $room = Room::query()->find($roomId);
        if (! $room) {
            throw new NotFoundError('اتاق مورد نظر یافت نشد.');
        }
        if ($room->owner_id !== $user->id && $user->role !== 'admin') {
            throw new NotFoundError('اتاق مورد نظر یافت نشد.');
        }

        return $room;
    }

    public function getRoomByPublicToken(string $token): Room
    {
        if ($token === '') {
            throw new NotFoundError('لینک تماشاگر نامعتبر است.');
        }
        $room = Room::query()
            ->where('public_token', $token)
            ->where('public_enabled', true)
            ->first();
        if (! $room) {
            throw new NotFoundError('اتاق عمومی یافت نشد یا دسترسی عمومی غیرفعال شده است.');
        }

        return $room;
    }

    // ── ساخت و ویرایش اتاق ────────────────────────────────────
    /** @param array<string, mixed> $data */
    public function createRoom(User $owner, array $data, string $ip = ''): Room
    {
        return DB::transaction(function () use ($owner, $data, $ip) {
            $lockedOwner = User::query()->where('id', $owner->id)->lockForUpdate()->firstOrFail();
            $roomsCount = Room::query()->where('owner_id', $lockedOwner->id)->count();
            if ($roomsCount >= (int) $this->settings->get('max_rooms_per_user')) {
                throw new QuotaExceededError(
                    'شما به سقف مجاز ساخت اتاق ('.$this->settings->get('max_rooms_per_user').' اتاق) رسیده‌اید.'
                );
            }

            $capacity = $this->validateCapacity((int) ($data['capacity'] ?? 10));
            $this->validateRoomText((string) $data['name'], (string) ($data['description'] ?? ''));
            $now = Mas::nowMs();

            $speakerMode = (bool) ($data['speaker_mode_enabled'] ?? false);
            $publicEnabled = (bool) ($data['public_enabled'] ?? false);

            $room = Room::create([
                'owner_id' => $lockedOwner->id,
                'name' => Mas::normalizePersianText($data['name']),
                'capacity' => $capacity,
                'description' => Mas::normalizePersianText($data['description'] ?? ''),
                'recording_enabled' => (bool) ($data['recording_enabled'] ?? false) && ! $speakerMode,
                'live_files_enabled' => (bool) ($data['live_files_enabled'] ?? false),
                'speaker_mode_enabled' => $speakerMode,
                'speaker_uploads_enabled' => $speakerMode && (bool) ($data['speaker_uploads_enabled'] ?? false),
                'timing_mode' => in_array($data['timing_mode'] ?? 'global', ['global', 'individual'], true) ? $data['timing_mode'] : 'global',
                'global_seconds' => max(10, min(86400, (int) ($data['global_seconds'] ?? 300))),
                'order_mode' => in_array($data['order_mode'] ?? 'manual', ['manual', 'alpha', 'age'], true) ? $data['order_mode'] : 'manual',
                'storage_used_bytes' => 0,
                'public_enabled' => $publicEnabled,
                'public_token' => $publicEnabled ? $this->security->generatePublicToken() : null,
                'public_token_created_at_ms' => $publicEnabled ? $now : 0,
                'created_at_ms' => $now,
                'updated_at_ms' => $now,
                'version' => 1,
            ]);

            // اسلات‌های اولیهٔ سخنران به تعداد ظرفیت
            for ($i = 0; $i < $capacity; $i++) {
                $speaker = Speaker::create([
                    'room_id' => $room->id,
                    'order_index' => $i,
                    'name' => '',
                    'gender' => '',
                    'description' => '',
                    'speaking_seconds' => $room->global_seconds,
                    'is_finished' => false,
                    'finished_at_ms' => 0,
                    'created_at_ms' => $now,
                    'updated_at_ms' => $now,
                ]);
                SpeakerTimerState::create([
                    'room_id' => $room->id,
                    'speaker_id' => $speaker->id,
                    'elapsed_ms' => 0,
                    'overtime_ms' => 0,
                    'started_at_ms' => 0,
                    'updated_at_ms' => $now,
                    'version' => 1,
                ]);
            }

            if ($room->speaker_mode_enabled) {
                foreach ($room->speakers()->get() as $speaker) {
                    $this->ensureSpeakerCode($room, $speaker);
                }
            }

            $first = $room->speakers()->first();
            RoomState::create([
                'room_id' => $room->id,
                'current_speaker_id' => $first?->id,
                'current_index' => 0,
                'running' => false,
                'awaiting_decision' => false,
                'started_at_ms' => 0,
                'elapsed_ms' => 0,
                'overtime_ms' => 0,
                'stop_reason' => '',
                'updated_at_ms' => $now,
                'version' => 1,
            ]);

            AuditLogger::log(
                'room_created',
                actorUserId: $lockedOwner->id,
                actorUsername: $lockedOwner->username,
                targetType: 'room',
                targetId: (string) $room->id,
                detail: ['name' => $room->name, 'capacity' => $room->capacity],
                ip: $ip,
            );

            return $room;
        });
    }

    /** @param array<string, mixed> $data */
    public function updateRoom(Room $roomParam, array $data, string $ip = ''): Room
    {
        return DB::transaction(function () use ($roomParam, $data) {
            $room = $this->lockRoom($roomParam->id);

            $targetSpeakerMode = ($data['speaker_mode_enabled'] ?? null) === null
                ? $room->speaker_mode_enabled
                : (bool) $data['speaker_mode_enabled'];
            $wasSpeakerMode = $room->speaker_mode_enabled;

            $hasActiveRecording = fn (bool $speakerScoped) => RecordingSession::query()
                ->where('room_id', $room->id)
                ->when($speakerScoped, fn ($q) => $q->whereNotNull('speaker_id'))
                ->whereIn('status', ['recording', 'paused', 'finalizing'])
                ->exists();

            if (! $wasSpeakerMode && $targetSpeakerMode && $hasActiveRecording(false)) {
                throw new AppError(
                    'پیش از فعال‌کردن حالت سخنران، ضبط فعلی را پایان دهید یا ذخیره کنید.',
                    code: 'ACTIVE_RECORDING_BLOCKS_SPEAKER_MODE',
                    statusCode: 409,
                );
            }
            if ($wasSpeakerMode && ! $targetSpeakerMode && $hasActiveRecording(true)) {
                throw new AppError(
                    'پیش از غیرفعال‌کردن حالت سخنران، ضبط‌های فعال/متوقف‌شدهٔ دستگاه‌ها را پایان دهید.',
                    code: 'ACTIVE_SPEAKER_RECORDING_BLOCKS_DISABLE',
                    statusCode: 409,
                );
            }
            $recordingEnabled = (bool) ($data['recording_enabled'] ?? false);
            if (! $recordingEnabled && ! $targetSpeakerMode && $hasActiveRecording(false)) {
                throw new AppError(
                    'تا زمانی که ضبط فعال این اتاق تعیین تکلیف نشده، امکان غیرفعال کردن ضبط وجود ندارد.',
                    code: 'ACTIVE_RECORDING_BLOCKS_DISABLE',
                    statusCode: 409,
                );
            }

            $this->validateRoomText((string) $data['name'], (string) ($data['description'] ?? ''));
            $capacity = $this->validateCapacity((int) $data['capacity']);
            $now = Mas::nowMs();

            $room->name = Mas::normalizePersianText($data['name']);
            $room->description = Mas::normalizePersianText($data['description'] ?? '');
            // در حالت سخنران ضبط روی دستگاه خود سخنران است؛ ضبط دوم روی دستگاه مالک هرگز شروع نمی‌شود.
            $room->recording_enabled = $recordingEnabled && ! $targetSpeakerMode;
            $room->live_files_enabled = (bool) ($data['live_files_enabled'] ?? false);
            $room->speaker_mode_enabled = $targetSpeakerMode;
            if (($data['speaker_uploads_enabled'] ?? null) !== null) {
                $room->speaker_uploads_enabled = (bool) $data['speaker_uploads_enabled'];
            }
            $room->timing_mode = in_array($data['timing_mode'] ?? 'global', ['global', 'individual'], true) ? $data['timing_mode'] : 'global';
            $room->global_seconds = max(10, min(86400, (int) ($data['global_seconds'] ?? 300)));
            $room->order_mode = in_array($data['order_mode'] ?? 'manual', ['manual', 'alpha', 'age'], true) ? $data['order_mode'] : 'manual';

            $speakers = $room->speakers()->get()->all();
            if ($targetSpeakerMode) {
                foreach ($speakers as $speaker) {
                    $this->ensureSpeakerCode($room, $speaker);
                }
            } elseif ($wasSpeakerMode) {
                foreach ($speakers as $speaker) {
                    $speaker->speaker_session_hash = null;
                    $speaker->presence_status = 'offline';
                    $speaker->save();
                }
            }

            $publicEnabled = (bool) ($data['public_enabled'] ?? false);
            if ($publicEnabled && ! $room->public_token) {
                $room->public_token = $this->security->generatePublicToken();
                $room->public_token_created_at_ms = $now;
            }
            $room->public_enabled = $publicEnabled;

            // مدیریت تغییر ظرفیت + محافظ C-04 (تأیید صریح برای حذف سخنران نام‌دار/فایل‌دار)
            $currentSpeakers = $speakers;
            if ($capacity < count($currentSpeakers)) {
                $toTruncate = array_slice($currentSpeakers, $capacity);
                $namedOrWithFiles = array_values(array_filter(
                    $toTruncate,
                    fn (Speaker $s) => trim($s->name) !== '' || $s->files()->exists(),
                ));
                $confirmShrink = (bool) ($data['confirm_shrink'] ?? false);
                if ($namedOrWithFiles !== [] && ! $confirmShrink) {
                    $names = array_map(
                        fn (Speaker $s) => $s->name,
                        array_filter($namedOrWithFiles, fn (Speaker $s) => trim($s->name) !== ''),
                    );
                    throw new AppError(
                        'کاهش ظرفیت منجر به حذف '.count($namedOrWithFiles).' سخنران ثبت‌شده ('
                        .implode(', ', array_slice($names, 0, 3))
                        .') یا فایل‌های اختصاصی آن‌ها می‌شود. لطفاً ابتدا تأیید کنید.',
                        code: 'CONFIRM_CAPACITY_SHRINK_REQUIRED',
                        details: ['affected_count' => count($namedOrWithFiles)],
                        statusCode: 409,
                    );
                }
                $truncateIds = array_map(fn (Speaker $s) => $s->id, $toTruncate);
                $activeForTruncated = RecordingSession::query()
                    ->where('room_id', $room->id)
                    ->whereIn('speaker_id', $truncateIds)
                    ->whereIn('status', ['recording', 'paused', 'finalizing'])
                    ->exists();
                if ($activeForTruncated) {
                    throw new AppError(
                        'برای کاهش ظرفیت ابتدا ضبط فعال سخنران موردنظر را پایان دهید.',
                        code: 'ACTIVE_RECORDING_BLOCKS_SHRINK',
                        statusCode: 409,
                    );
                }
                $lockedOwner = $this->lockOwner($room->owner_id);
                foreach ($toTruncate as $sp) {
                    foreach ($sp->files()->get() as $f) {
                        if ($f->upload_type !== 'recording') {
                            CleanupQueue::enqueue($f->backend, $f->storage_key, 'capacity_shrink');
                            $room->storage_used_bytes = max(0, $room->storage_used_bytes - $f->size_bytes);
                            if ($lockedOwner) {
                                $lockedOwner->storage_used_bytes = max(0, $lockedOwner->storage_used_bytes - $f->size_bytes);
                                $lockedOwner->save();
                            }
                            // رفع B-03: ردیف فایل هم حذف می‌شود؛ ضبط‌ها عمداً با SET NULL می‌مانند.
                            $f->delete();
                        }
                    }
                    $sp->delete();
                }
            } elseif ($capacity > count($currentSpeakers)) {
                $startIdx = count($currentSpeakers);
                for ($i = 0; $i < $capacity - count($currentSpeakers); $i++) {
                    $sp = Speaker::create([
                        'room_id' => $room->id,
                        'order_index' => $startIdx + $i,
                        'name' => '',
                        'gender' => '',
                        'description' => '',
                        'speaking_seconds' => $room->global_seconds,
                        'is_finished' => false,
                        'finished_at_ms' => 0,
                        'created_at_ms' => $now,
                        'updated_at_ms' => $now,
                    ]);
                    SpeakerTimerState::create([
                        'room_id' => $room->id,
                        'speaker_id' => $sp->id,
                        'elapsed_ms' => 0,
                        'overtime_ms' => 0,
                        'started_at_ms' => 0,
                        'updated_at_ms' => $now,
                        'version' => 1,
                    ]);
                    if ($targetSpeakerMode) {
                        $this->ensureSpeakerCode($room, $sp);
                    }
                }
            }

            $room->capacity = $capacity;

            // همگام‌سازی RoomState با اولین سخنران معتبر بعد از تغییر ترکیب
            $state = $room->state()->first();
            if ($state) {
                $speakersNow = $room->speakers()->get()->all();
                $current = null;
                foreach ($speakersNow as $s) {
                    if ($s->id === $state->current_speaker_id) {
                        $current = $s;
                        break;
                    }
                }
                if ($current === null) {
                    foreach ($speakersNow as $s) {
                        if (! $s->is_finished) {
                            $current = $s;
                            break;
                        }
                    }
                    $current ??= ($speakersNow[0] ?? null);
                    $state->current_speaker_id = $current?->id;
                    $state->current_index = $current ? array_search($current, $speakersNow, true) : 0;
                    $state->running = false;
                    $state->awaiting_decision = false;
                    $state->started_at_ms = 0;
                    $timer = $current?->timer()->first();
                    $state->elapsed_ms = $timer?->elapsed_ms ?? 0;
                    $state->overtime_ms = $timer?->overtime_ms ?? 0;
                    $state->stop_reason = $current ? 'switched' : '';
                } else {
                    $state->current_index = array_search($current, $speakersNow, true);
                }
                $state->version += 1;
                $state->updated_at_ms = $now;
                $state->save();
            }

            self::applyRoomSpeakerOrder($room);

            $room->updated_at_ms = $now;
            $room->version += 1;
            $room->save();

            return $room;
        });
    }

    public function rotatePublicToken(Room $room): string
    {
        $room->public_token = $this->security->generatePublicToken();
        $room->public_token_created_at_ms = Mas::nowMs();
        $room->public_enabled = true;
        $room->save();

        return $room->public_token;
    }

    public function generateQrSvg(string $url): string
    {
        return QrCode::format('svg')->size(240)->margin(2)->generate($url);
    }

    public function deleteRoom(Room $roomParam, User $actor, string $ip = ''): void
    {
        DB::transaction(function () use ($roomParam, $actor, $ip) {
            $room = $this->lockRoom($roomParam->id);
            foreach ($room->files()->get() as $f) {
                CleanupQueue::enqueue($f->backend, $f->storage_key, 'room_deleted');
            }
            $recordingIds = RecordingSession::query()->where('room_id', $room->id)->pluck('id');
            if ($recordingIds->isNotEmpty()) {
                foreach (RecordingChunk::query()->whereIn('session_id', $recordingIds)->get() as $c) {
                    CleanupQueue::enqueue($c->backend, $c->storage_key, 'room_deleted');
                }
            }
            $owner = $this->lockOwner($room->owner_id);
            if ($owner) {
                $owner->storage_used_bytes = max(0, $owner->storage_used_bytes - $room->storage_used_bytes);
                $owner->save();
            }
            AuditLogger::log(
                'room_deleted',
                actorUserId: $actor->id,
                actorUsername: $actor->username,
                severity: 'warning',
                targetType: 'room',
                targetId: (string) $room->id,
                detail: ['name' => $room->name],
                ip: $ip,
            );
            $room->delete();
        });
    }

    // ── فایل‌ها ───────────────────────────────────────────────
    /**
     * آپلود جریانی فایل مشترک/اختصاصی با سقف سخت و رعایت اتمیک سهمیه‌ها.
     *
     * @param  resource  $stream
     */
    public function uploadSpeechFile(
        Room $room,
        string $uploadType,
        string $filename,
        $stream,
        ?int $speakerId = null,
        string $approvalStatus = 'approved',
    ): SpeechFile {
        if (! in_array($uploadType, ['common', 'speaker'], true)) {
            throw new ValidationAppError('نوع آپلود نامعتبر است.');
        }
        if (! in_array($approvalStatus, ['pending', 'approved', 'rejected'], true)) {
            throw new ValidationAppError('وضعیت تأیید فایل نامعتبر است.');
        }
        if ($uploadType === 'speaker' && $speakerId === null) {
            throw new ValidationAppError('فایل اختصاصی باید به یک سخنران متصل باشد.');
        }

        $cleanFilename = Mas::sanitizeFilename($filename, 'file.bin');
        $dotPos = strrpos($cleanFilename, '.');
        $ext = $dotPos === false ? '' : strtolower(substr($cleanFilename, $dotPos));
        if (! in_array($ext, $this->settings->allowedExtensions(), true)) {
            throw new FileUploadError(
                "فرمت فایل مجاز نیست ({$ext}). فرمت‌های مجاز: ".implode(', ', $this->settings->allowedExtensions())
            );
        }

        $now = Mas::nowMs();
        $safeKey = "files/{$room->id}/{$now}_".bin2hex(random_bytes(8))."_{$cleanFilename}";

        // ذخیرهٔ جریانی با سقف سخت: به‌محض عبور از سقف، نوشتن متوقف و فایل موقت پاک می‌شود.
        try {
            [$sizeBytes, $sha256] = $this->storage->saveStream($safeKey, $stream, $this->settings->maxUploadBytes());
        } catch (\Throwable $e) {
            try {
                $this->storage->delete($safeKey);
            } catch (\Throwable) {
                // best-effort
            }
            throw $e;
        }

        return DB::transaction(function () use (
            $room, $uploadType, $cleanFilename, $ext, $safeKey, $sizeBytes, $sha256, $speakerId, $approvalStatus, $now
        ) {
            $lockedRoom = $this->lockRoom($room->id);
            $owner = $this->lockOwner($lockedRoom->owner_id);
            $activeStatuses = ['recording', 'paused', 'finalizing'];

            $roomReserved = (int) RecordingSession::query()
                ->where('room_id', $lockedRoom->id)
                ->whereIn('status', $activeStatuses)
                ->sum('bytes_received');
            if ($lockedRoom->storage_used_bytes + $roomReserved + $sizeBytes > $this->settings->maxRoomStorageBytes()) {
                $this->deleteQuietly($safeKey);
                throw new QuotaExceededError('فضای ذخیره‌سازی اختصاص داده شده به این اتاق برای این فایل کافی نیست.');
            }

            $ownerReserved = 0;
            if ($owner) {
                $ownerReserved = (int) RecordingSession::query()
                    ->join('rooms', 'rooms.id', '=', 'recording_sessions.room_id')
                    ->where('rooms.owner_id', $owner->id)
                    ->whereIn('recording_sessions.status', $activeStatuses)
                    ->sum('recording_sessions.bytes_received');
            }
            if ($owner && $owner->storage_used_bytes + $ownerReserved + $sizeBytes > $this->settings->maxUserStorageBytes()) {
                $this->deleteQuietly($safeKey);
                throw new QuotaExceededError('سقف کل فضای حساب کاربری شما با احتساب ضبط‌های در حال دریافت کافی نیست.');
            }

            $available = $this->storage->availableBytes();
            if ($available !== null && $sizeBytes > max(0, $available - 64 * 1024 * 1024)) {
                $this->deleteQuietly($safeKey);
                throw new QuotaExceededError('فضای خالی دیسک برای ذخیرهٔ این فایل کافی نیست.');
            }

            $speakerName = '';
            if ($speakerId !== null) {
                $speaker = Speaker::query()
                    ->where('id', $speakerId)->where('room_id', $lockedRoom->id)
                    ->first();
                if (! $speaker) {
                    $this->deleteQuietly($safeKey);
                    throw new NotFoundError('سخنران مورد نظر متعلق به این اتاق نیست.');
                }
                $speakerName = $speaker->name;
            }

            try {
                $file = SpeechFile::create([
                    'room_id' => $lockedRoom->id,
                    'speaker_id' => $speakerId,
                    'filename' => $cleanFilename,
                    'storage_key' => $safeKey,
                    'backend' => (string) $this->settings->get('storage_backend'),
                    'content_type' => self::SAFE_MIME_BY_EXTENSION[$ext] ?? 'application/octet-stream',
                    'size_bytes' => $sizeBytes,
                    'upload_type' => $uploadType,
                    'approval_status' => $approvalStatus,
                    'speaker_name' => $speakerName,
                    'sha256' => $sha256,
                    'created_at_ms' => $now,
                    'updated_at_ms' => $now,
                ]);
            } catch (\Throwable $e) {
                $this->deleteQuietly($safeKey);
                throw $e;
            }

            $lockedRoom->storage_used_bytes += $sizeBytes;
            $lockedRoom->save();
            if ($owner) {
                $owner->storage_used_bytes += $sizeBytes;
                $owner->save();
            }

            return $file;
        });
    }

    public function reviewSpeechFile(Room $roomParam, int $fileId, bool $approved): SpeechFile
    {
        return DB::transaction(function () use ($roomParam, $fileId, $approved) {
            $room = $this->lockRoom($roomParam->id);
            $file = SpeechFile::query()
                ->where('id', $fileId)->where('room_id', $room->id)
                ->lockForUpdate()->first();
            if (! $file || $file->upload_type !== 'speaker') {
                throw new NotFoundError('فایل سخنران مورد نظر یافت نشد.');
            }
            $file->approval_status = $approved ? 'approved' : 'rejected';
            $file->updated_at_ms = Mas::nowMs();
            $file->save();

            return $file;
        });
    }

    public function deleteSpeechFile(Room $roomParam, int $fileId): void
    {
        DB::transaction(function () use ($roomParam, $fileId) {
            $room = $this->lockRoom($roomParam->id);
            $file = SpeechFile::query()
                ->where('id', $fileId)->where('room_id', $room->id)
                ->first();
            if (! $file) {
                throw new NotFoundError('فایل مورد نظر یافت نشد.');
            }
            $room->storage_used_bytes = max(0, $room->storage_used_bytes - $file->size_bytes);
            $room->save();
            $owner = $this->lockOwner($room->owner_id);
            if ($owner) {
                $owner->storage_used_bytes = max(0, $owner->storage_used_bytes - $file->size_bytes);
                $owner->save();
            }
            CleanupQueue::enqueue($file->backend, $file->storage_key, 'user_deleted');
            $file->delete();
        });
    }

    private function deleteQuietly(string $key): void
    {
        try {
            $this->storage->delete($key);
        } catch (\Throwable) {
            // best-effort؛ صف پاک‌سازی بعداً جمعش می‌کند.
        }
    }
}
