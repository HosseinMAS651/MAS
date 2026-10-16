<?php

namespace App\Http\Controllers\Api;

use App\Exceptions\ConflictError;
use App\Exceptions\ForbiddenError;
use App\Exceptions\NotFoundError;
use App\Exceptions\QuotaExceededError;
use App\Exceptions\UnauthorizedError;
use App\Exceptions\ValidationAppError;
use App\Http\Controllers\Controller;
use App\Http\Requests\RecordingStartRequest;
use App\Http\Requests\SpeakerEnterRequest;
use App\Http\Requests\SpeakerHeartbeatRequest;
use App\Http\Requests\SpeakerRecordingFinishRequest;
use App\Models\RecordingSession;
use App\Models\Room;
use App\Models\Speaker;
use App\Presenters\MasPresenter;
use App\Services\RateLimiter;
use App\Services\RecordingService;
use App\Services\RoomService;
use App\Services\SecurityService;
use App\Services\SpeakerAccessService;
use App\Services\TimerService;
use App\Support\Settings;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

/**
 * معادل mas_app/api/routers/speaker_access.py — ورود با کد ۴کاراکتری و
 * نشست دستگاه سخنران زیر /api/public/{token}/speaker.
 */
class SpeakerAccessController extends Controller
{
    public function __construct(
        private readonly RoomService $roomService,
        private readonly SpeakerAccessService $speakerAccess,
        private readonly RecordingService $recordingService,
        private readonly TimerService $timerService,
        private readonly SecurityService $security,
        private readonly Settings $settings,
    ) {
    }

    /** @return array{0: Room, 1: Speaker} */
    private function context(Request $request): array
    {
        $room = $request->attributes->get('mas_room');
        $speaker = $request->attributes->get('speaker_device');
        if (! $room instanceof Room || ! $speaker instanceof Speaker) {
            throw new UnauthorizedError('نشست سخنران منقضی شده یا با ورود دستگاه دیگری جایگزین شده است.');
        }

        return [$room, $speaker];
    }

    public function enter(SpeakerEnterRequest $request, string $token): JsonResponse
    {
        $room = $this->roomService->getRoomByPublicToken($token);
        $bucketKey = "speaker-code:room:{$room->id}:ip:".$this->security->extractClientIp($request);
        // شمارنده حتی روی خطای ۴۲۹ هم commit می‌شود (داخل خود RateLimiter).
        RateLimiter::checkAndIncrement(
            $bucketKey,
            'speaker_code_entry',
            (int) $this->settings->get('speaker_code_max_attempts'),
            (int) $this->settings->get('speaker_code_window_seconds'),
        );

        $result = $this->speakerAccess->enter($room, (string) $request->validated()['code']);
        if ($result === null) {
            throw new UnauthorizedError('کد سخنران نادرست است یا حالت سخنران فعال نیست.');
        }
        [$speaker, $rawToken] = $result;
        RateLimiter::reset($bucketKey);

        return response()->json([
            'ok' => true,
            'session_token' => $rawToken,
            'speaker' => [
                'id' => $speaker->id,
                'name' => $speaker->name,
                'presence_status' => $speaker->presence_status,
            ],
            'speaker_uploads_enabled' => $room->speaker_uploads_enabled,
        ]);
    }

    public function heartbeat(SpeakerHeartbeatRequest $request, string $token): JsonResponse
    {
        [, $speaker] = $this->context($request);
        $status = $this->speakerAccess->heartbeat(
            $speaker,
            (bool) ($request->validated()['microphone_ready'] ?? false),
        );

        return response()->json(['ok' => true, 'presence_status' => $status]);
    }

    public function leave(Request $request, string $token): JsonResponse
    {
        [, $speaker] = $this->context($request);
        $this->speakerAccess->leave($speaker);

        return response()->json(['ok' => true]);
    }

    public function recordingStart(RecordingStartRequest $request, string $token): JsonResponse
    {
        [$room, $speaker] = $this->context($request);
        if ($speaker->presence_status !== 'ready') {
            throw new ConflictError('برای ضبط ابتدا دسترسی میکروفون را فعال کنید.', code: 'MICROPHONE_NOT_READY');
        }
        $snapshot = $this->timerService->getSnapshot($room);
        if (! $snapshot['running'] || $snapshot['current_speaker_id'] !== $speaker->id) {
            throw new ConflictError('ضبط فقط هنگام فعال بودن تایمر همین سخنران آغاز می‌شود.', code: 'SPEAKER_TURN_NOT_ACTIVE');
        }
        $recording = $this->recordingService->startOrResume(
            $room,
            $speaker,
            (string) ($request->validated()['mime_type'] ?? 'audio/webm'),
        );

        return response()->json([
            'ok' => true,
            'session_id' => $recording->id,
            'status' => $recording->status,
            'mime_type' => $recording->mime_type,
            'next_seq' => $recording->chunk_seq,
        ]);
    }

    public function recordingChunk(Request $request, string $token): JsonResponse
    {
        [$room, $speaker] = $this->context($request);
        $uploaded = $request->file('chunk');
        if (! $uploaded) {
            throw new ValidationAppError('تکهٔ ارسالی خالی است.');
        }
        if ($uploaded->getSize() > $this->recordingService->settings->maxRecordingChunkBytes()) {
            throw new QuotaExceededError('اندازهٔ تکه از سقف مجاز بزرگ‌تر است.');
        }
        $data = file_get_contents($uploaded->getRealPath());
        if ($data === false || $data === '') {
            throw new ValidationAppError('تکهٔ ارسالی خالی است.');
        }

        $sessionId = (int) $request->input('session_id');
        $seq = (int) $request->input('seq');
        $belongs = RecordingSession::query()
            ->where('id', $sessionId)
            ->where('room_id', $room->id)
            ->where('speaker_id', $speaker->id)
            ->exists();
        if (! $belongs) {
            throw new NotFoundError('نشست ضبط متعلق به این سخنران یافت نشد.');
        }

        $saved = $this->recordingService->saveChunk($sessionId, $seq, $data, $room->id);

        return response()->json([
            'ok' => true,
            'session_id' => $saved->session_id,
            'seq' => $saved->seq,
            'bytes_received' => $saved->size_bytes,
        ]);
    }

    public function recordingFinish(SpeakerRecordingFinishRequest $request, string $token): JsonResponse
    {
        [$room, $speaker] = $this->context($request);
        $data = $request->validated();
        $recording = RecordingSession::query()
            ->where('id', $data['session_id'])
            ->where('room_id', $room->id)
            ->where('speaker_id', $speaker->id)
            ->first();
        if (! $recording) {
            throw new NotFoundError('نشست ضبط متعلق به این سخنران یافت نشد.');
        }
        // پاسخ finish برای نشست تمام‌شده idempotent است.
        if (in_array($recording->status, ['saved', 'discarded'], true)) {
            $file = $recording->finalFile;

            return response()->json([
                'ok' => true,
                'file' => $file ? MasPresenter::file($file) : null,
                'status' => $recording->status,
            ]);
        }
        if (! ($data['save'] ?? true)) {
            $this->recordingService->discardRecording($recording);

            return response()->json(['ok' => true, 'file' => null, 'status' => 'discarded']);
        }
        $finalFile = $this->recordingService->finishAndSave($recording);

        return response()->json([
            'ok' => true,
            'file' => $finalFile ? MasPresenter::file($finalFile) : null,
            'status' => $finalFile ? 'saved' : 'discarded',
        ]);
    }

    public function uploadFile(Request $request, string $token): JsonResponse
    {
        [$room, $speaker] = $this->context($request);
        if (! $room->speaker_uploads_enabled) {
            throw new ForbiddenError('مالک اتاق آپلود فایل توسط سخنران را فعال نکرده است.');
        }
        $uploaded = $request->file('file');
        if (! $uploaded) {
            throw new ValidationAppError('فایل ارسالی یافت نشد.');
        }
        $stream = fopen($uploaded->getRealPath(), 'rb');
        try {
            $file = $this->roomService->uploadSpeechFile(
                $room,
                'speaker',
                $uploaded->getClientOriginalName() ?: 'file',
                $stream,
                $speaker->id,
                'pending',
            );
        } finally {
            if (is_resource($stream)) {
                fclose($stream);
            }
        }

        return response()->json([
            'ok' => true,
            'file' => MasPresenter::file($file),
            'review' => 'pending',
        ]);
    }
}
