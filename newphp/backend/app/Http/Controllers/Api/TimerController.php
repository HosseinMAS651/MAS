<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\TimerActionRequest;
use App\Models\Room;
use App\Presenters\MasPresenter;
use App\Services\RoomService;
use App\Services\TimerService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/** معادل mas_app/api/routers/timer.py — وضعیت تایمر با ETag/304 و اکشن‌ها. */
class TimerController extends Controller
{
    public function __construct(
        private readonly RoomService $roomService,
        private readonly TimerService $timerService,
    ) {
    }

    /** ETag snapshot؛ فقط سازگاری داخلی لازم است، نه برابری با هش Python. */
    private function snapshotEtag(Room $room, array $snapshot): string
    {
        $speakers = [];
        foreach ($snapshot['speakers'] as $s) {
            $timer = $s->timer;
            $speakers[] = [
                'id' => $s->id,
                'order' => $s->order_index,
                'finished' => $s->is_finished,
                'elapsed' => $timer?->elapsed_ms ?? 0,
                'overtime' => $timer?->overtime_ms ?? 0,
                'updated' => $s->updated_at_ms,
            ];
        }
        $payload = [
            'room_version' => $room->version,
            'state_version' => $snapshot['version'],
            'running' => $snapshot['running'],
            'awaiting_decision' => $snapshot['awaiting_decision'],
            'stop_reason' => $snapshot['stop_reason'],
            'current_speaker_id' => $snapshot['current_speaker_id'],
            'elapsed_s' => intdiv($snapshot['elapsed_ms'], 1000),
            'overtime_s' => intdiv($snapshot['overtime_ms'], 1000),
            'limit_ms' => $snapshot['limit_ms'],
            'speakers' => $speakers,
            'recording_status' => $snapshot['recording_status'],
        ];

        return '"'.hash('sha256', json_encode($payload)).'"';
    }

    public function state(Request $request, int $roomId): Response
    {
        $room = $this->roomService->getRoomForUser($roomId, $request->attributes->get('mas_user'));
        $snapshot = $this->timerService->getSnapshot($room);

        $etag = $this->snapshotEtag($room, $snapshot);
        $headers = ['ETag' => $etag, 'Cache-Control' => 'no-cache, must-revalidate'];

        if ($request->headers->get('if-none-match') === $etag) {
            return new Response('', 304, $headers);
        }

        return response()->json(
            ['ok' => true, 'state' => MasPresenter::timerState($room, $snapshot)],
            200,
            $headers,
        );
    }

    public function action(TimerActionRequest $request, int $roomId): JsonResponse
    {
        $room = $this->roomService->getRoomForUser($roomId, $request->attributes->get('mas_user'));
        $data = $request->validated();
        $snapshot = $this->timerService->handleAction(
            $room,
            $data['action'],
            $data['speaker_id'] ?? null,
            $data['expected_version'] ?? null,
        );

        return response()->json(['ok' => true, 'state' => MasPresenter::timerState($room, $snapshot)]);
    }
}
