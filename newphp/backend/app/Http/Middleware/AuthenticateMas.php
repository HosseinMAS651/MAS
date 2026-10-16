<?php

namespace App\Http\Middleware;

use App\Exceptions\UnauthorizedError;
use App\Services\AuthService;
use App\Support\Settings;
use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/**
 * معادل get_current_user/get_current_active_user در deps.py:
 * توکن از کوکی HttpOnly یا هدر Bearer خوانده و کاربر+نشست روی request گذاشته می‌شود.
 */
class AuthenticateMas
{
    public function __construct(
        private readonly AuthService $authService,
        private readonly Settings $settings,
    ) {
    }

    public function handle(Request $request, Closure $next): Response
    {
        $token = $request->cookie((string) $this->settings->get('cookie_name', 'mas_session'));
        $authorization = (string) $request->headers->get('authorization', '');
        if ((! $token) && str_starts_with($authorization, 'Bearer ')) {
            $token = trim(substr($authorization, 7));
        }
        if (! $token) {
            throw new UnauthorizedError('لطفاً ابتدا وارد حساب کاربری خود شوید.');
        }

        [$user, $session] = $this->authService->getUserFromToken((string) $token, touch: true);
        if (! $user->is_active) {
            throw new UnauthorizedError('حساب کاربری شما غیرفعال شده است.');
        }

        $request->attributes->set('mas_user', $user);
        $request->attributes->set('mas_session', $session);

        return $next($request);
    }
}
