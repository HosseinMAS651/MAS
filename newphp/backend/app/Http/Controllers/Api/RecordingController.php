<?php

namespace App\Http\Controllers\Api;

use App\Exceptions\ConflictError;
use App\Exceptions\ForbiddenError;
use App\Exceptions\NotFoundError;
use App\Exceptions\ValidationAppError;
use App\Http\Controllers\Controller;
use App\Http\Requests\RecordingFinishRequest;
use App\Http\Requests\RecordingStartRequest;
use App\Presenters\MasPresenter;
use App\Services\RecordingService;
use App\Services\RoomService;
use App\Services\TimerService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

/** معادل mas_app/api/routers/recording.py — ضبط روی دستگاه مالک. */
class RecordingController extends Controller
{
    public function __construct(
        private readonly RoomService $roomService,
        private readonly RecordingService $recordingService,
        private readonly TimerService $timerService,
    ) {
    }

    public function start(RecordingStartRequest $request, int $roomId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $request->attributes->get('mas_user'));
        if ($room->speaker_mode_enabled || ! $room->recording_enabled) {
            throw new ForbiddenError('این اتاق ضبط را از دستگاه سخنران انجام می‌دهد، نه دستگاه مالک.');
        }
        $snapshot = $this->timerService->getSnapshot($room);
        $speaker = $snapshot['current_speaker'];
        if (! $snapshot['running'] || ! $speaker) {
            throw new ConflictError('ضبط فقط هنگام اجرای تایمر آغاز می‌شود.', code: 'TIMER_NOT_RUNNING');
        }
        $recording = $this->recordingService->startOrResume(
            $room, $speaker, $request->validated()['mime_type'] ?? 'audio/webm',
        );

        return response()->json([
            'ok' => true,
            'session_id' => $recording->id,
            'status' => $recording->status,
            'mime_type' => $recording->mime_type,
            'next_seq' => $recording->chunk_seq,
        ]);
    }

    public function status(Request $request, int $roomId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $request->attributes->get('mas_user'));
        $rec = $this->recordingService->getActiveSession($room->id);
        if (! $rec) {
            return response()->json(['ok' => true, 'active' => false, 'session' => null]);
        }

        return response()->json([
            'ok' => true,
            'active' => true,
            'session' => [
                'session_id' => $rec->id,
                'room_id' => $rec->room_id,
                'speaker_id' => $rec->speaker_id,
                'speaker_name' => $rec->speaker_name,
                'status' => $rec->status,
                'chunk_seq' => $rec->chunk_seq,
                'bytes_received' => $rec->bytes_received,
                'recorded_ms' => $rec->recorded_ms,
                'active' => in_array($rec->status, ['recording', 'paused'], true),
            ],
        ]);
    }

    public function chunk(Request $request, int $roomId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $request->attributes->get('mas_user'));
        $uploaded = $request->file('chunk');
        if (! $uploaded) {
            throw new ValidationAppError('تکهٔ ارسالی خالی است.');
        }
        $max = $this->recordingService->settings->maxRecordingChunkBytes();
        if ($uploaded->getSize() > $max) {
            throw new ValidationAppError('اندازهٔ تکه از سقف مجاز بزرگ‌تر است.');
        }
        $data = file_get_contents($uploaded->getRealPath());
        if ($data === false || $data === '') {
            throw new ValidationAppError('تکهٔ ارسالی خالی است.');
        }
        $chunk = $this->recordingService->saveChunk(
            (int) $request->input('session_id'),
            (int) $request->input('seq'),
            $data,
            $room->id,
        );

        return response()->json([
            'ok' => true,
            'chunk' => [
                'session_id' => $chunk->session_id,
                'seq' => $chunk->seq,
                'bytes_received' => $chunk->size_bytes,
                'status' => 'saved',
            ],
        ]);
    }

    public function finish(RecordingFinishRequest $request, int $roomId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $request->attributes->get('mas_user'));
        $rec = $this->recordingService->getActiveSession($room->id);
        if (! $rec) {
            throw new NotFoundError('هیچ ضبط فعالی برای این اتاق یافت نشد.');
        }
        $save = $request->validated()['save'] ?? true;
        if (! $save) {
            $this->recordingService->discardRecording($rec);

            return response()->json(['ok' => true, 'message' => 'ضبط با موفقیت دور ریخته شد.']);
        }
        $finalFile = $this->recordingService->finishAndSave($rec);

        return response()->json([
            'ok' => true,
            'message' => 'ضبط با موفقیت مونتاژ و ذخیره شد.',
            'file' => $finalFile ? MasPresenter::file($finalFile) : null,
        ]);
    }
}
