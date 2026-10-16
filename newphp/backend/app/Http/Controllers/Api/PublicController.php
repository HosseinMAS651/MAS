<?php

namespace App\Http\Controllers\Api;

use App\Exceptions\ForbiddenError;
use App\Exceptions\NotFoundError;
use App\Http\Controllers\Controller;
use App\Models\RoomState;
use App\Models\SpeechFile;
use App\Presenters\MasPresenter;
use App\Services\PdfReportService;
use App\Services\RateLimiter;
use App\Services\ReactionService;
use App\Services\RoomService;
use App\Services\SecurityService;
use App\Services\SpeechFileResponder;
use App\Services\TimerService;
use App\Support\Settings;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/** معادل mas_app/api/routers/public.py — اتاق تماشاگران بدون لاگین. */
class PublicController extends Controller
{
    private const INLINE_SAFE_TYPES = [
        'application/pdf',
        'text/plain; charset=utf-8',
        'text/markdown; charset=utf-8',
        'text/csv; charset=utf-8',
    ];

    public function __construct(
        private readonly RoomService $roomService,
        private readonly TimerService $timerService,
        private readonly SpeechFileResponder $fileResponder,
        private readonly ReactionService $reactions,
        private readonly PdfReportService $pdfReport,
        private readonly SecurityService $security,
        private readonly Settings $settings,
    ) {
    }

    private function publicDisposition(SpeechFile $file, string $contentType): string
    {
        $safeInline = in_array($contentType, self::INLINE_SAFE_TYPES, true)
            || str_starts_with($contentType, 'image/')
            || str_starts_with($contentType, 'audio/')
            || str_starts_with($contentType, 'video/');
        $disposition = $safeInline ? 'inline' : 'attachment';

        return "{$disposition}; filename*=UTF-8''".rawurlencode($file->filename);
    }

    public function state(Request $request, string $token): Response
    {
        $room = $this->roomService->getRoomByPublicToken($token);
        $snapshot = $this->timerService->getSnapshot($room);

        $liveFilesVersion = [];
        if ($room->live_files_enabled) {
            foreach ($room->files as $f) {
                if (in_array($f->upload_type, ['common', 'speaker'], true) && $f->approval_status === 'approved') {
                    $liveFilesVersion[] = [$f->id, $f->updated_at_ms];
                }
            }
        }
        $speakerRows = [];
        foreach ($snapshot['speakers'] as $s) {
            $t = $s->timer;
            $speakerRows[] = [$s->id, $s->order_index, $s->is_finished, $t?->elapsed_ms ?? 0, $t?->overtime_ms ?? 0, $s->updated_at_ms];
        }
        $etagPayload = [
            'room_version' => $room->version,
            'state_version' => $snapshot['version'],
            'running' => $snapshot['running'],
            'awaiting' => $snapshot['awaiting_decision'],
            'current' => $snapshot['current_speaker_id'],
            'elapsed_s' => intdiv($snapshot['elapsed_ms'], 1000),
            'overtime_s' => intdiv($snapshot['overtime_ms'], 1000),
            'limit_ms' => $snapshot['limit_ms'],
            'speaker_mode_enabled' => $room->speaker_mode_enabled,
            'speaker_uploads_enabled' => $room->speaker_uploads_enabled,
            'speakers' => $speakerRows,
            'live_files_version' => $liveFilesVersion,
        ];
        $etag = '"'.hash('sha256', json_encode($etagPayload)).'"';
        $cacheControl = 'public, max-age='.(int) $this->settings->get('public_state_max_age_seconds').', must-revalidate';
        $headers = ['ETag' => $etag, 'Cache-Control' => $cacheControl];

        if ($request->headers->get('if-none-match') === $etag) {
            return new Response('', 304, $headers);
        }

        // فقط snapshotهای تغییرکرده شمرده می‌شوند؛ پولینگ شرطی سهمیهٔ جدا ندارد.
        RateLimiter::checkAndIncrement(
            "public:room:{$room->id}:state:ip:".$this->security->extractClientIp($request),
            'public_state',
            (int) $this->settings->get('public_max_per_ip'),
            (int) $this->settings->get('public_window_seconds'),
        );

        return response()->json(
            ['ok' => true, 'state' => MasPresenter::publicState($room, $snapshot)],
            200,
            $headers,
        );
    }

    public function file(Request $request, string $token, int $fileId): Response
    {
        $room = $this->roomService->getRoomByPublicToken($token);
        if (! $room->live_files_enabled) {
            throw new ForbiddenError('نمایش فایل‌های زنده در این اتاق مجاز نیست.');
        }
        RateLimiter::checkAndIncrement(
            "public:room:{$room->id}:file:ip:".$this->security->extractClientIp($request),
            'public_file',
            (int) $this->settings->get('public_max_per_ip'),
            (int) $this->settings->get('public_window_seconds'),
        );

        $file = SpeechFile::query()
            ->where('id', $fileId)->where('room_id', $room->id)
            ->whereIn('upload_type', ['common', 'speaker'])
            ->where('approval_status', 'approved')
            ->first();
        if (! $file) {
            throw new NotFoundError('فایل مورد نظر یافت نشد.');
        }
        // فایل اختصاصی فقط وقتی عمومی است که همان سخنران در حال اجرا باشد.
        if ($file->upload_type === 'speaker') {
            $currentId = RoomState::query()->where('room_id', $room->id)->value('current_speaker_id');
            if ($currentId !== $file->speaker_id) {
                throw new NotFoundError('فایل مورد نظر در حال حاضر برای تماشاگران قابل نمایش نیست.');
            }
        }

        $contentType = MasPresenter::publicContentType($file);
        $headers = [
            'Content-Disposition' => $this->publicDisposition($file, $contentType),
            'Cache-Control' => 'no-store, max-age=0',
            'X-Content-Type-Options' => 'nosniff',
        ];

        return $this->fileResponder->respond(
            $file, $headers, $contentType, $request->headers->get('range'),
        );
    }

    public function qr(Request $request, string $token): Response
    {
        $room = $this->roomService->getRoomByPublicToken($token);
        RateLimiter::checkAndIncrement(
            "public:room:{$room->id}:qr:ip:".$this->security->extractClientIp($request),
            'public_qr',
            (int) $this->settings->get('public_max_per_ip'),
            (int) $this->settings->get('public_window_seconds'),
        );
        $baseUrl = (string) $this->settings->get('public_base_url', '');
        if ($baseUrl === '') {
            $baseUrl = $request->getSchemeAndHttpHost();
        }
        $svg = $this->roomService->generateQrSvg(rtrim($baseUrl, '/')."/public/{$room->public_token}");

        return new Response($svg, 200, ['Content-Type' => 'image/svg+xml']);
    }

    public function sendReaction(Request $request, string $token): JsonResponse
    {
        $room = $this->roomService->getRoomByPublicToken($token);
        if (! $this->reactions->isEnabled($room->id)) {
            throw new ForbiddenError('ارسال واکنش برای این جلسه موقتاً غیرفعال است.');
        }
        RateLimiter::checkAndIncrement(
            "reaction:room:{$room->id}:ip:".$this->security->extractClientIp($request),
            'reaction_post',
            (int) $this->settings->get('reaction_max_per_minute'),
            60,
        );
        $emoji = trim((string) $request->input('emoji', 'heart'));
        $item = $this->reactions->addReaction($room->id, $emoji);

        return response()->json(['ok' => true, 'reaction' => $item]);
    }

    public function recentReactions(Request $request, string $token): JsonResponse
    {
        $room = $this->roomService->getRoomByPublicToken($token);
        RateLimiter::checkAndIncrement(
            "reaction-poll:room:{$room->id}:ip:".$this->security->extractClientIp($request),
            'reaction_poll',
            (int) $this->settings->get('reaction_poll_max_per_minute'),
            60,
        );

        return response()->json([
            'ok' => true,
            'reactions_enabled' => $this->reactions->isEnabled($room->id),
            'reactions' => $this->reactions->getRecent($room->id, 3.0),
            'totals' => $this->reactions->getTotals($room->id),
        ]);
    }

    public function reportPdf(Request $request, string $token): Response
    {
        $room = $this->roomService->getRoomByPublicToken($token);
        RateLimiter::checkAndIncrement(
            "public:room:{$room->id}:report:ip:".$this->security->extractClientIp($request),
            'public_report',
            (int) $this->settings->get('public_max_per_ip'),
            (int) $this->settings->get('public_window_seconds'),
        );
        // گزارش عمومی رویدادهای ممیزی را شامل نمی‌شود (مثل نسخهٔ Python).
        $pdf = $this->pdfReport->generateRoomReport(
            $room, [], $this->reactions->getTotals($room->id),
            includeFiles: $room->live_files_enabled,
        );
        $filename = "report-room-{$room->id}.pdf";

        return new Response($pdf, 200, [
            'Content-Type' => 'application/pdf',
            'Content-Disposition' => "attachment; filename*=UTF-8''".rawurlencode($filename),
            'Cache-Control' => 'no-cache',
        ]);
    }
}
