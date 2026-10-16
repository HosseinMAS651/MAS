<?php

namespace App\Http\Controllers\Api;

use App\Exceptions\NotFoundError;
use App\Exceptions\ValidationAppError;
use App\Http\Controllers\Controller;
use App\Http\Requests\SpeakerReorderRequest;
use App\Http\Requests\SpeakerUpdateRequest;
use App\Models\Speaker;
use App\Presenters\MasPresenter;
use App\Services\RecordingService;
use App\Services\RoomService;
use App\Services\SpeakerService;
use App\Support\Settings;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

/** معادل mas_app/api/routers/speakers.py */
class SpeakerController extends Controller
{
    public function __construct(
        private readonly RoomService $roomService,
        private readonly SpeakerService $speakerService,
        private readonly RecordingService $recordingService,
        private readonly Settings $settings,
    ) {
    }

    private function validateSpeakerText(SpeakerUpdateRequest $request): void
    {
        if (mb_strlen(trim((string) $request->input('name', ''))) > (int) $this->settings->get('max_speaker_name_length')) {
            throw new ValidationAppError(
                'نام سخنران نمی‌تواند بیش از '.$this->settings->get('max_speaker_name_length').' نویسه باشد.'
            );
        }
        if (mb_strlen((string) $request->input('description', '')) > (int) $this->settings->get('max_description_length')) {
            throw new ValidationAppError(
                'توضیحات نمی‌تواند بیش از '.$this->settings->get('max_description_length').' نویسه باشد.'
            );
        }
    }

    public function store(SpeakerUpdateRequest $request, int $roomId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $request->attributes->get('mas_user'));
        $this->validateSpeakerText($request);
        $data = $request->validated();
        $speaker = $this->speakerService->addSpeaker(
            $room,
            name: $data['name'] ?? '',
            gender: $data['gender'] ?? '',
            age: $data['age'] ?? null,
            description: $data['description'] ?? '',
            speakingSeconds: $data['speaking_seconds'] ?? null,
        );
        if ($room->speaker_mode_enabled) {
            $this->roomService->ensureSpeakerCode($room, $speaker);
            $speaker->save();
        }

        return response()->json(['ok' => true, 'speaker' => MasPresenter::speaker($speaker)]);
    }

    public function update(SpeakerUpdateRequest $request, int $roomId, int $speakerId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $request->attributes->get('mas_user'));
        $this->validateSpeakerText($request);
        $speaker = Speaker::query()->where('id', $speakerId)->where('room_id', $room->id)->first();
        if (! $speaker) {
            throw new NotFoundError('سخنران مورد نظر یافت نشد.');
        }
        $data = $request->validated();
        $updated = $this->speakerService->updateSpeaker(
            $speaker,
            name: $data['name'] ?? '',
            gender: $data['gender'] ?? '',
            age: $data['age'] ?? null,
            description: $data['description'] ?? '',
            speakingSeconds: $data['speaking_seconds'] ?? null,
        );

        return response()->json(['ok' => true, 'speaker' => MasPresenter::speaker($updated)]);
    }

    public function destroy(Request $request, int $roomId, int $speakerId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $request->attributes->get('mas_user'));
        $save = $request->query('save_recording');
        $this->speakerService->deleteSpeaker(
            $room,
            $speakerId,
            $save === null ? null : filter_var($save, FILTER_VALIDATE_BOOL),
            $this->recordingService,
        );

        return response()->json(['ok' => true, 'message' => 'سخنران با موفقیت حذف شد.']);
    }

    public function reorder(SpeakerReorderRequest $request, int $roomId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $request->attributes->get('mas_user'));
        $this->speakerService->reorderSpeakers($room, $request->validated()['speaker_ids']);

        return response()->json(['ok' => true, 'message' => 'ترتیب سخنران‌ها به‌روزرسانی شد.']);
    }

    public function rotateCode(Request $request, int $roomId, int $speakerId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $request->attributes->get('mas_user'));
        if (! $room->speaker_mode_enabled) {
            throw new ValidationAppError('ابتدا حالت سخنران را در تنظیمات اتاق فعال کنید.');
        }
        $code = $this->roomService->rotateSpeakerCode($room, $speakerId);

        return response()->json(['ok' => true, 'speaker_id' => $speakerId, 'speaker_code' => $code]);
    }

    public function unfreeze(Request $request, int $roomId, int $speakerId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $request->attributes->get('mas_user'));
        $speaker = $this->speakerService->unfreezeSpeaker($room, $speakerId);

        return response()->json(['ok' => true, 'speaker' => MasPresenter::speaker($speaker)]);
    }

    public function resetAll(Request $request, int $roomId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $request->attributes->get('mas_user'));
        $this->speakerService->resetAllSpeakers($room, $this->recordingService);

        return response()->json(['ok' => true, 'message' => 'تمام سخنران‌ها و تایمرها بازنشانی شدند.']);
    }
}
