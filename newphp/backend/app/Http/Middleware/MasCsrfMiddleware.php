<?php

namespace App\Http\Middleware;

use App\Models\AuthSession;
use App\Services\SecurityService;
use App\Support\Settings;
use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/**
 * معادل api/csrf.py: برای درخواست‌های تغییردهندهٔ cookie-authenticated،
 * هدر X-CSRF-Token باید با هش ذخیره‌شدهٔ نشست یکی باشد.
 * لاگین/ثبت‌نام/بازیابی و فراخوانی‌های Bearer معاف‌اند.
 */
class MasCsrfMiddleware
{
    private const SAFE_METHODS = ['GET', 'HEAD', 'OPTIONS'];

    private const EXEMPT_PATHS = [
        '/api/auth/login',
        '/api/auth/register',
        '/api/auth/recover-password',
    ];

    public function __construct(
        private readonly Settings $settings,
        private readonly SecurityService $security,
    ) {
    }

    public function handle(Request $request, Closure $next): Response
    {
        if (! $this->settings->get('csrf_protection_enabled', true)) {
            return $next($request);
        }
        $path = '/'.ltrim($request->path(), '/');
        if (in_array($request->method(), self::SAFE_METHODS, true)
            || ! str_starts_with($path, '/api/')
            || in_array($path, self::EXEMPT_PATHS, true)) {
            return $next($request);
        }

        $sessionToken = $request->cookie((string) $this->settings->get('cookie_name', 'mas_session'));
        if (! $sessionToken) {
            // بدون کوکی، خطای احراز هویت در لایهٔ خودش برمی‌گردد.
            return $next($request);
        }
        $authorization = strtolower((string) $request->headers->get('authorization', ''));
        if (str_starts_with($authorization, 'bearer ')) {
            return $next($request);
        }

        $csrfToken = trim((string) $request->headers->get('x-csrf-token', ''));
        if ($csrfToken === '') {
            return $this->reject('CSRF_TOKEN_MISSING');
        }

        $session = AuthSession::query()
            ->where('token_hash', $this->security->hashToken((string) $sessionToken))
            ->first();
        if (! $session || ! $this->security->verifyCsrf($csrfToken, $session->csrf_hash)) {
            return $this->reject('CSRF_TOKEN_INVALID');
        }

        return $next($request);
    }

    private function reject(string $code): Response
    {
        return response()->json([
            'ok' => false,
            'error' => [
                'code' => $code,
                'message' => 'درخواست امنیتی معتبر نیست. لطفاً صفحه را تازه‌سازی کنید.',
                'details' => new \stdClass,
            ],
        ], 403);
    }
}
