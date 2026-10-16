<?php

namespace App\Http\Middleware;

use App\Exceptions\UnauthorizedError;
use App\Services\RoomService;
use App\Services\SpeakerAccessService;
use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/**
 * معادل _speaker_context در speaker_access.py: اتاق از توکن عمومی مسیر و
 * سخنران از توکن Bearer نشست دستگاه resolve می‌شود (انقضای حضور در سرویس
 * نشست را باطل می‌کند).
 */
class AuthenticateSpeakerDevice
{
    public function __construct(
        private readonly RoomService $roomService,
        private readonly SpeakerAccessService $speakerAccess,
    ) {
    }

    public function handle(Request $request, Closure $next): Response
    {
        $room = $this->roomService->getRoomByPublicToken((string) $request->route('token'));

        $rawToken = '';
        $authorization = (string) $request->headers->get('authorization', '');
        if (preg_match('/^Bearer\s+(.+)$/i', $authorization, $m)) {
            $rawToken = trim($m[1]);
        }

        $speaker = $rawToken !== '' ? $this->speakerAccess->authenticate($room, $rawToken) : null;
        if (! $speaker) {
            throw new UnauthorizedError('نشست سخنران منقضی شده یا با ورود دستگاه دیگری جایگزین شده است.');
        }

        $request->attributes->set('mas_room', $room);
        $request->attributes->set('speaker_device', $speaker);

        return $next($request);
    }
}
