<?php

namespace App\Http\Controllers\Api;

use App\Exceptions\NotFoundError;
use App\Exceptions\ValidationAppError;
use App\Http\Controllers\Controller;
use App\Http\Requests\FileReviewRequest;
use App\Http\Requests\RoomStoreRequest;
use App\Http\Requests\RoomUpdateRequest;
use App\Models\AuditLog;
use App\Models\SpeechFile;
use App\Presenters\MasPresenter;
use App\Services\PdfReportService;
use App\Services\ReactionService;
use App\Services\RoomService;
use App\Services\SecurityService;
use App\Services\SpeechFileResponder;
use App\Services\TimerService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/** معادل mas_app/api/routers/rooms.py */
class RoomController extends Controller
{
    public function __construct(
        private readonly RoomService $roomService,
        private readonly TimerService $timerService,
        private readonly SpeechFileResponder $fileResponder,
        private readonly ReactionService $reactions,
        private readonly PdfReportService $pdfReport,
        private readonly SecurityService $security,
    ) {
    }

    private function user(Request $request)
    {
        return $request->attributes->get('mas_user');
    }

    public function index(Request $request): JsonResponse
    {
        $rooms = $this->roomService->listRoomsForUser($this->user($request)->id);

        return response()->json([
            'ok' => true,
            'rooms' => array_map(fn ($r) => MasPresenter::roomSummary($r), $rooms),
        ]);
    }

    public function store(RoomStoreRequest $request): JsonResponse
    {
        $room = $this->roomService->createRoom(
            $this->user($request),
            $request->validated(),
            $this->security->extractClientIp($request),
        );

        return response()->json(['ok' => true, 'room' => MasPresenter::roomSummary($room)]);
    }

    public function show(Request $request, int $roomId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $this->user($request));
        $this->roomService->expireSpeakerPresence($room);
        $snapshot = $this->timerService->getSnapshot($room);
        $currentId = $snapshot['current_speaker_id'];

        $speakers = [];
        foreach ($room->speakers as $s) {
            $isCurrent = $s->id === $currentId;
            $speakers[] = MasPresenter::ownerSpeaker(
                $s,
                $room->speaker_mode_enabled ? $this->roomService->speakerCodeForOwner($s) : null,
                $isCurrent ? $snapshot['elapsed_ms'] : null,
                $isCurrent ? $snapshot['overtime_ms'] : null,
            );
        }

        $files = [];
        $recordings = [];
        foreach ($room->files as $f) {
            if ($f->upload_type === 'recording') {
                $recordings[] = MasPresenter::file($f);
            } else {
                $files[] = MasPresenter::file($f);
            }
        }

        $summary = MasPresenter::roomSummary($room);
        $summary['public_token'] = $room->public_token;
        $summary['speakers'] = $speakers;
        $summary['files'] = $files;
        $summary['recordings'] = $recordings;

        return response()->json(['ok' => true, 'room' => $summary]);
    }

    public function update(RoomUpdateRequest $request, int $roomId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $this->user($request));
        $updated = $this->roomService->updateRoom(
            $room,
            $request->validated(),
            $this->security->extractClientIp($request),
        );

        return response()->json(['ok' => true, 'room' => MasPresenter::roomSummary($updated)]);
    }

    public function destroy(Request $request, int $roomId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $this->user($request));
        $this->roomService->deleteRoom($room, $this->user($request), $this->security->extractClientIp($request));

        return response()->json(['ok' => true, 'message' => 'اتاق و کلیه فایل‌های آن با موفقیت حذف شدند.']);
    }

    public function rotatePublicToken(Request $request, int $roomId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $this->user($request));

        return response()->json([
            'ok' => true,
            'public_token' => $this->roomService->rotatePublicToken($room),
        ]);
    }

    public function qr(Request $request, int $roomId): Response
    {
        $room = $this->roomService->getRoomForUser($roomId, $this->user($request));
        if (! $room->public_enabled || ! $room->public_token) {
            throw new ValidationAppError('ابتدا دسترسی عمومی اتاق را فعال کنید.');
        }
        $baseUrl = (string) $this->roomService->settings->get('public_base_url', '');
        if ($baseUrl === '') {
            $baseUrl = $request->getSchemeAndHttpHost();
        }
        $svg = $this->roomService->generateQrSvg(rtrim($baseUrl, '/')."/public/{$room->public_token}");

        return new Response($svg, 200, ['Content-Type' => 'image/svg+xml']);
    }

    public function uploadFile(Request $request, int $roomId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $this->user($request));
        $uploaded = $request->file('file');
        if (! $uploaded) {
            throw new ValidationAppError('فایل ارسالی یافت نشد.');
        }
        $stream = fopen($uploaded->getRealPath(), 'rb');
        try {
            $file = $this->roomService->uploadSpeechFile(
                $room,
                uploadType: (string) $request->input('upload_type', 'common'),
                filename: $uploaded->getClientOriginalName() ?: 'file',
                stream: $stream,
                speakerId: $request->input('speaker_id') !== null ? (int) $request->input('speaker_id') : null,
            );
        } finally {
            if (is_resource($stream)) {
                fclose($stream);
            }
        }

        return response()->json(['ok' => true, 'file' => MasPresenter::file($file)]);
    }

    public function reviewFile(FileReviewRequest $request, int $roomId, int $fileId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $this->user($request));
        $file = $this->roomService->reviewSpeechFile($room, $fileId, (bool) $request->validated()['approved']);

        return response()->json(['ok' => true, 'file' => MasPresenter::file($file)]);
    }

    public function deleteFile(Request $request, int $roomId, int $fileId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $this->user($request));
        $this->roomService->deleteSpeechFile($room, $fileId);

        return response()->json(['ok' => true, 'message' => 'فایل با موفقیت حذف شد.']);
    }

    public function download(Request $request, int $roomId, int $fileId): Response
    {
        $room = $this->roomService->getRoomForUser($roomId, $this->user($request));
        $file = SpeechFile::query()->where('id', $fileId)->where('room_id', $room->id)->first();
        if (! $file) {
            throw new NotFoundError('فایل مورد نظر یافت نشد.');
        }
        $headers = [
            'Content-Disposition' => "attachment; filename*=UTF-8''".rawurlencode($file->filename),
        ];

        return $this->fileResponder->respond(
            $file, $headers, $file->content_type, $request->headers->get('range'),
        );
    }

    public function play(Request $request, int $roomId, int $fileId): Response
    {
        $room = $this->roomService->getRoomForUser($roomId, $this->user($request));
        $file = SpeechFile::query()
            ->where('id', $fileId)->where('room_id', $room->id)
            ->where('upload_type', 'recording')
            ->first();
        if (! $file) {
            throw new NotFoundError('ضبط صوتی مورد نظر یافت نشد.');
        }
        if (! str_starts_with($file->content_type, 'audio/')) {
            throw new ValidationAppError('این فایل از نوع صوتی قابل پخش نیست.');
        }
        $headers = [
            'Content-Disposition' => "inline; filename*=UTF-8''".rawurlencode($file->filename),
            'Cache-Control' => 'private, no-store',
            'X-Content-Type-Options' => 'nosniff',
        ];

        return $this->fileResponder->respond(
            $file, $headers, $file->content_type, $request->headers->get('range'),
        );
    }

    public function reportPdf(Request $request, int $roomId): Response
    {
        $room = $this->roomService->getRoomForUser($roomId, $this->user($request));
        $logs = AuditLog::query()
            ->where('target_type', 'room')->where('target_id', (string) $room->id)
            ->orderByDesc('id')->limit(30)->get();
        $events = $logs->map(fn (AuditLog $log) => [
            'action' => $log->action,
            'detail' => $log->detail,
            'created_at_ms' => $log->created_at_ms,
        ])->all();

        $pdf = $this->pdfReport->generateRoomReport(
            $room, $events, $this->reactions->getTotals($room->id),
        );
        $filename = "report-room-{$room->id}.pdf";

        return new Response($pdf, 200, [
            'Content-Type' => 'application/pdf',
            'Content-Disposition' => "attachment; filename*=UTF-8''".rawurlencode($filename),
            'Cache-Control' => 'no-cache',
        ]);
    }

    public function toggleReactions(Request $request, int $roomId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $this->user($request));
        $newState = ! $this->reactions->isEnabled($room->id);
        $this->reactions->setEnabled($room->id, $newState);

        return response()->json(['ok' => true, 'reactions_enabled' => $newState]);
    }
}
