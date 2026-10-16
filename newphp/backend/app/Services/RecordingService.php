<?php

namespace App\Services;

use App\Exceptions\ConflictError;
use App\Exceptions\NotFoundError;
use App\Exceptions\QuotaExceededError;
use App\Exceptions\RecordingError;
use App\Models\CleanupQueue;
use App\Models\RecordingChunk;
use App\Models\RecordingSession;
use App\Models\Room;
use App\Models\Speaker;
use App\Models\SpeechFile;
use App\Models\User;
use App\Services\Storage\StorageBackend;
use App\Support\Mas;
use App\Support\Settings;
use Illuminate\Support\Facades\DB;

/**
 * معادل mas_app/services/recording_service.py — ضبط تکه‌ای قابل اتکا با
 * ترتیب سخت‌گیرانهٔ seq، سهمیهٔ رزروشده و نهایی‌سازی دقیقاً یک‌باره.
 * ترتیب قفل‌ها همه‌جا: اتاق ← نشست ضبط ← مالک (جلوگیری از بن‌بست).
 */
class RecordingService
{
    public const ACTIVE_STATUSES = ['recording', 'paused'];

    public const BLOCKING_STATUSES = ['recording', 'paused', 'finalizing'];

    public function __construct(
        public readonly Settings $settings,
        private readonly StorageBackend $storage,
    ) {
    }

    private function lockRoom(int $roomId): Room
    {
        $room = Room::query()->where('id', $roomId)->lockForUpdate()->first();
        if (! $room) {
            throw new NotFoundError('اتاق مورد نظر یافت نشد.');
        }

        return $room;
    }

    public function getActiveSession(
        int $roomId,
        ?int $speakerId = null,
        bool $lock = false,
        bool $includeFinalizing = false,
    ): ?RecordingSession {
        $statuses = $includeFinalizing ? self::BLOCKING_STATUSES : self::ACTIVE_STATUSES;
        $query = RecordingSession::query()
            ->where('room_id', $roomId)
            ->whereIn('status', $statuses)
            ->orderByDesc('id');
        if ($speakerId !== null) {
            $query->where('speaker_id', $speakerId);
        }
        if ($lock) {
            $query->lockForUpdate();
        }

        return $query->first();
    }

    public static function normalizeMimeType(?string $mimeType): string
    {
        $mime = strtolower(trim(explode(';', (string) $mimeType)[0]));

        return in_array($mime, [
            'audio/webm', 'audio/mp4', 'audio/ogg', 'audio/wav', 'audio/x-wav',
            'audio/mpeg', 'audio/aac', 'audio/flac',
        ], true) ? $mime : 'audio/webm';
    }

    public function startOrResume(Room $room, Speaker $speaker, string $mimeType = 'audio/webm'): RecordingSession
    {
        if (! ($room->recording_enabled || $room->speaker_mode_enabled)) {
            throw new RecordingError('قابلیت ضبط صدا برای این اتاق فعال نیست.');
        }
        $normalized = self::normalizeMimeType($mimeType);

        return DB::transaction(function () use ($room, $speaker, $normalized) {
            $lockedRoom = $this->lockRoom($room->id);
            $blocking = $this->getActiveSession($lockedRoom->id, $speaker->id, lock: true, includeFinalizing: true);
            if ($blocking && $blocking->status === 'finalizing') {
                throw new ConflictError(
                    'ضبط دیگری در حال ذخیره‌سازی است؛ لطفاً کمی بعد دوباره تلاش کنید.',
                    code: 'RECORDING_FINALIZING',
                );
            }
            if ($blocking && $blocking->speaker_id !== $speaker->id) {
                throw new ConflictError('هم‌زمان فقط ضبط یک سخنران امکان‌پذیر است.', code: 'ACTIVE_RECORDING_EXISTS');
            }

            $rec = $blocking;
            $now = Mas::nowMs();
            if ($rec === null) {
                $name = trim($speaker->name) !== '' ? trim($speaker->name) : 'سخنران '.($speaker->order_index + 1);
                $rec = RecordingSession::create([
                    'room_id' => $lockedRoom->id,
                    'speaker_id' => $speaker->id,
                    'speaker_name' => mb_substr($name, 0, 120),
                    'status' => 'recording',
                    'mime_type' => $normalized,
                    'chunk_seq' => 0,
                    'bytes_received' => 0,
                    'recorded_ms' => 0,
                    'active_since_ms' => $now,
                    'started_at_ms' => $now,
                    'last_chunk_at_ms' => $now,
                    'ended_at_ms' => 0,
                    'error' => '',
                    'version' => 1,
                ]);

                return $rec;
            }

            if ($rec->chunk_seq === 0) {
                $rec->mime_type = $normalized;
            }
            if ($rec->status === 'paused') {
                $rec->status = 'recording';
                $rec->active_since_ms = $now;
                $rec->error = '';
                $rec->version += 1;
                $rec->save();
            }

            return $rec;
        });
    }

    public function pause(int $roomId, ?int $speakerId = null): void
    {
        DB::transaction(function () use ($roomId, $speakerId) {
            $rec = $this->getActiveSession($roomId, $speakerId, lock: true);
            if (! $rec || $rec->status !== 'recording') {
                return;
            }
            $now = Mas::nowMs();
            if ($rec->active_since_ms > 0) {
                $rec->recorded_ms += max(0, $now - $rec->active_since_ms);
            }
            $rec->recorded_ms = min($rec->recorded_ms, $this->settings->maxRecordingSeconds() * 1000);
            $rec->active_since_ms = 0;
            $rec->status = 'paused';
            $rec->version += 1;
            $rec->save();
        });
    }

    /** @param string $chunkData دادهٔ خام تکه (در PHP وب‌سرور آن را کامل دریافت کرده است). */
    public function saveChunk(int $sessionId, int $seq, string $chunkData, int $roomId): RecordingChunk
    {
        if ($seq < 0) {
            throw new RecordingError('شمارهٔ تکه نامعتبر است.');
        }
        if ($chunkData === '') {
            throw new RecordingError('تکهٔ ارسالی خالی است.');
        }
        if (strlen($chunkData) > $this->settings->maxRecordingChunkBytes()) {
            throw new QuotaExceededError('اندازهٔ تکه از سقف مجاز آپلود ضبط بیشتر است.');
        }
        if (strlen($chunkData) > $this->settings->maxRecordingBytes()) {
            throw new QuotaExceededError('اندازهٔ تکهٔ ضبط غیرمجاز است.');
        }
        $length = strlen($chunkData);

        return DB::transaction(function () use ($sessionId, $seq, $chunkData, $roomId, $length) {
            $room = $this->lockRoom($roomId);
            $rec = RecordingSession::query()
                ->where('id', $sessionId)->where('room_id', $roomId)
                ->lockForUpdate()->first();
            if (! $rec) {
                throw new NotFoundError('نشست ضبط متعلق به این اتاق یافت نشد.');
            }
            if (! in_array($rec->status, self::ACTIVE_STATUSES, true)) {
                throw new RecordingError("امکان ارسال تکه برای ضبط در وضعیت {$rec->status} وجود ندارد.");
            }

            $existing = RecordingChunk::query()
                ->where('session_id', $rec->id)->where('seq', $seq)
                ->first();
            if ($existing) {
                return $existing; // ارسال تکراری همان seq بی‌اثر است.
            }
            if ($seq !== $rec->chunk_seq) {
                throw new RecordingError("ترتیب تکه‌ها نامعتبر است؛ تکهٔ بعدی باید {$rec->chunk_seq} باشد.");
            }
            if ($rec->chunk_seq >= (int) $this->settings->get('recording_max_chunks')) {
                throw new RecordingError('حداکثر تعداد تکه‌های مجاز برای این ضبط پر شده است.');
            }
            if ($rec->bytes_received + $length > $this->settings->maxRecordingBytes()) {
                throw new QuotaExceededError('حجم کل ضبط از سقف مجاز سرور فراتر رفته است.');
            }

            $activeStatuses = self::BLOCKING_STATUSES;
            $roomReserved = (int) RecordingSession::query()
                ->where('room_id', $room->id)->whereIn('status', $activeStatuses)
                ->sum('bytes_received');
            if ($room->storage_used_bytes + $roomReserved + $length > $this->settings->maxRoomStorageBytes()) {
                throw new QuotaExceededError('سقف فضای اتاق برای دریافت این تکهٔ ضبط کافی نیست.');
            }

            $owner = User::query()->where('id', $room->owner_id)->lockForUpdate()->first();
            if ($owner) {
                $ownerReserved = (int) RecordingSession::query()
                    ->join('rooms', 'rooms.id', '=', 'recording_sessions.room_id')
                    ->where('rooms.owner_id', $owner->id)
                    ->whereIn('recording_sessions.status', $activeStatuses)
                    ->sum('recording_sessions.bytes_received');
                if ($owner->storage_used_bytes + $ownerReserved + $length > $this->settings->maxUserStorageBytes()) {
                    throw new QuotaExceededError('سقف کل فضای حساب برای دریافت این تکهٔ ضبط کافی نیست.');
                }
            }

            $available = $this->storage->availableBytes();
            if ($available !== null && $length > max(0, $available - 8 * 1024 * 1024)) {
                throw new QuotaExceededError('فضای خالی دیسک برای دریافت این تکهٔ ضبط کافی نیست.');
            }

            $chunkKey = "chunks/{$rec->room_id}/{$rec->id}/".sprintf('%08d', $seq).'.bin';
            [$sizeBytes] = $this->storage->saveBytes($chunkKey, $chunkData);
            try {
                $chunk = RecordingChunk::create([
                    'session_id' => $rec->id,
                    'seq' => $seq,
                    'storage_key' => $chunkKey,
                    'backend' => (string) $this->settings->get('storage_backend'),
                    'size_bytes' => $sizeBytes,
                    'created_at_ms' => Mas::nowMs(),
                ]);
                $rec->chunk_seq = $seq + 1;
                $rec->bytes_received += $sizeBytes;
                $rec->last_chunk_at_ms = Mas::nowMs();
                $rec->version += 1;
                $rec->save();

                return $chunk;
            } catch (\Throwable $e) {
                try {
                    $this->storage->delete($chunkKey);
                } catch (\Throwable) {
                }
                throw $e;
            }
        });
    }

    private static function extensionForMime(string $mimeType): string
    {
        $mime = strtolower(trim(explode(';', $mimeType)[0]));

        return [
            'audio/webm' => '.webm',
            'audio/ogg' => '.ogg',
            'audio/mp4' => '.m4a',
            'audio/mpeg' => '.mp3',
            'audio/wav' => '.wav',
            'audio/x-wav' => '.wav',
        ][$mime] ?? '.webm';
    }

    private function localDateString(Room $room, int $nowMs): string
    {
        $tzName = $room->owner()->first()?->timezone ?: 'UTC';
        try {
            $tz = new \DateTimeZone($tzName);
        } catch (\Throwable) {
            $tz = new \DateTimeZone('UTC');
        }
        $when = (new \DateTimeImmutable('@'.intdiv($nowMs, 1000)))->setTimezone($tz);

        return $when->format('Ymd_His');
    }

    public function finishAndSave(RecordingSession $recSession): ?SpeechFile
    {
        return DB::transaction(function () use ($recSession) {
            $room = $this->lockRoom($recSession->room_id);
            $rec = RecordingSession::query()
                ->where('id', $recSession->id)->where('room_id', $room->id)
                ->lockForUpdate()->first();
            if (! $rec) {
                throw new NotFoundError('نشست ضبط یافت نشد.');
            }
            if (in_array($rec->status, ['saved', 'discarded'], true)) {
                return $rec->finalFile()->first();
            }
            if ($rec->status === 'finalizing') {
                throw new ConflictError('این ضبط هم‌زمان در حال ذخیره‌سازی است.', code: 'RECORDING_FINALIZING');
            }
            if (! in_array($rec->status, self::ACTIVE_STATUSES, true)) {
                throw new RecordingError("امکان نهایی‌سازی ضبط در وضعیت {$rec->status} وجود ندارد.");
            }

            $now = Mas::nowMs();
            if ($rec->status === 'recording' && $rec->active_since_ms > 0) {
                $rec->recorded_ms += max(0, $now - $rec->active_since_ms);
                $rec->active_since_ms = 0;
            }
            $rec->recorded_ms = min($rec->recorded_ms, $this->settings->maxRecordingSeconds() * 1000);

            $chunks = $rec->chunks()->get()->all();
            if ($chunks === []) {
                $rec->status = 'discarded';
                $rec->ended_at_ms = $now;
                $rec->version += 1;
                $rec->save();

                return null;
            }

            $sequences = array_map(fn (RecordingChunk $c) => $c->seq, $chunks);
            if ($sequences !== range(0, count($chunks) - 1) || $rec->chunk_seq !== count($chunks)) {
                $this->failSession($rec, 'دادهٔ ضبط ناقص یا نامرتب است.', $now);
                throw new RecordingError('ترتیب یا تعداد تکه‌های ضبط کامل نیست؛ فایل ذخیره نشد.');
            }

            $owner = User::query()->where('id', $room->owner_id)->lockForUpdate()->first();
            $totalExpected = array_sum(array_map(fn (RecordingChunk $c) => $c->size_bytes, $chunks));
            if ($totalExpected !== $rec->bytes_received) {
                $this->failSession($rec, 'حجم ثبت‌شده با مجموع تکه‌های ضبط یکسان نیست.', $now);
                throw new RecordingError('اطلاعات ضبط ناسازگار است؛ فایل ذخیره نشد.');
            }

            $roomReserved = (int) RecordingSession::query()
                ->where('room_id', $room->id)->where('id', '!=', $rec->id)
                ->whereIn('status', self::BLOCKING_STATUSES)->sum('bytes_received');
            if ($room->storage_used_bytes + $roomReserved + $totalExpected > $this->settings->maxRoomStorageBytes()) {
                $this->pauseSession($rec, 'سقف فضای اتاق برای ذخیرهٔ ضبط و نشست‌های دیگر کافی نیست.');
                throw new QuotaExceededError('فضای اتاق با احتساب ضبط‌های دیگر برای ذخیرهٔ این فایل کافی نیست.');
            }

            $ownerReserved = 0;
            if ($owner) {
                $ownerReserved = (int) RecordingSession::query()
                    ->join('rooms', 'rooms.id', '=', 'recording_sessions.room_id')
                    ->where('rooms.owner_id', $owner->id)
                    ->where('recording_sessions.id', '!=', $rec->id)
                    ->whereIn('recording_sessions.status', self::BLOCKING_STATUSES)
                    ->sum('recording_sessions.bytes_received');
            }
            if ($owner && $owner->storage_used_bytes + $ownerReserved + $totalExpected > $this->settings->maxUserStorageBytes()) {
                $this->pauseSession($rec, 'سقف فضای حساب با احتساب ضبط‌های دیگر برای ذخیره کافی نیست.');
                throw new QuotaExceededError('سقف فضای حساب با احتساب فایل‌های ذخیره‌شده و ضبط‌های در حال دریافت کافی نیست.');
            }

            $available = $this->storage->availableBytes();
            if ($available !== null && $totalExpected + 64 * 1024 * 1024 > $available) {
                $this->pauseSession($rec, 'فضای خالی دیسک برای ساخت فایل نهایی کافی نیست.');
                throw new QuotaExceededError('فضای خالی دیسک برای ذخیرهٔ ضبط کافی نیست.');
            }

            $speakerName = $rec->speaker_name !== '' ? $rec->speaker_name : 'بدون نام';
            $dateStr = $this->localDateString($room, $now);
            $ext = self::extensionForMime($rec->mime_type);
            $displayFilename = mb_substr(
                Mas::sanitizeFilename($room->name, 'اتاق').' - '
                .Mas::sanitizeFilename($speakerName, 'سخنران')." - {$dateStr}{$ext}",
                0, 255,
            );
            $safeDisplay = Mas::sanitizeFilename($displayFilename, 'recording');
            $targetKey = "recordings/{$room->id}/{$rec->id}_{$safeDisplay}";
            $chunkKeys = array_map(fn (RecordingChunk $c) => $c->storage_key, $chunks);

            $rec->status = 'finalizing';
            $rec->version += 1;
            $rec->save();

            try {
                [$totalSize, $sha256] = $this->storage->assembleChunks($targetKey, $chunkKeys);
                if ($totalSize !== $totalExpected) {
                    throw new RecordingError('حجم فایل نهایی با مجموع تکه‌های ضبط یکسان نیست.');
                }
                $speechFile = SpeechFile::create([
                    'room_id' => $room->id,
                    'speaker_id' => $rec->speaker_id,
                    'filename' => $displayFilename,
                    'storage_key' => $targetKey,
                    'backend' => (string) $this->settings->get('storage_backend'),
                    'content_type' => explode(';', $rec->mime_type ?: 'audio/webm')[0],
                    'size_bytes' => $totalSize,
                    'upload_type' => 'recording',
                    'approval_status' => 'approved',
                    'duration_ms' => $rec->recorded_ms,
                    'speaker_name' => mb_substr($speakerName, 0, 120),
                    'sha256' => $sha256,
                    'created_at_ms' => $now,
                    'updated_at_ms' => $now,
                ]);
            } catch (\Throwable $e) {
                try {
                    $this->storage->delete($targetKey);
                } catch (\Throwable) {
                    CleanupQueue::enqueue((string) $this->settings->get('storage_backend'), $targetKey, 'recording_assembly_failed');
                }
                $rec->status = 'paused';
                $rec->error = mb_substr($e->getMessage(), 0, 255);
                $rec->active_since_ms = 0;
                $rec->ended_at_ms = 0;
                $rec->version += 1;
                $rec->save();
                if ($e instanceof RecordingError) {
                    throw $e;
                }
                throw new RecordingError('مونتاژ و ذخیرهٔ فایل ضبط ناموفق بود؛ ضبط برای تلاش مجدد نگه داشته شد.', previous: $e);
            }

            $rec->status = 'saved';
            $rec->ended_at_ms = $now;
            $rec->final_file_id = $speechFile->id;
            $rec->error = '';
            $rec->version += 1;
            $rec->save();

            $room->storage_used_bytes += $totalSize;
            $room->save();
            if ($owner) {
                $owner->storage_used_bytes += $totalSize;
                $owner->save();
            }
            foreach ($chunks as $c) {
                CleanupQueue::enqueue($c->backend, $c->storage_key, 'chunk_assembled');
            }

            return $speechFile;
        });
    }

    private function failSession(RecordingSession $rec, string $error, int $now): void
    {
        $rec->status = 'failed';
        $rec->error = $error;
        $rec->ended_at_ms = $now;
        $rec->active_since_ms = 0;
        $rec->version += 1;
        $rec->save();
    }

    private function pauseSession(RecordingSession $rec, string $error): void
    {
        $rec->status = 'paused';
        $rec->error = $error;
        $rec->version += 1;
        $rec->save();
    }

    public function discardRecording(RecordingSession $recSession): void
    {
        DB::transaction(function () use ($recSession) {
            $rec = RecordingSession::query()->where('id', $recSession->id)->lockForUpdate()->first();
            if (! $rec || in_array($rec->status, ['saved', 'discarded'], true)) {
                return;
            }
            foreach ($rec->chunks()->get() as $c) {
                CleanupQueue::enqueue($c->backend, $c->storage_key, 'recording_discarded');
            }
            $rec->status = 'discarded';
            $rec->ended_at_ms = Mas::nowMs();
            $rec->active_since_ms = 0;
            $rec->error = '';
            $rec->version += 1;
            $rec->save();
        });
    }
}
