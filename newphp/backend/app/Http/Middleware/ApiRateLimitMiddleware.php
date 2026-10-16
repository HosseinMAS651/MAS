<?php

namespace App\Http\Middleware;

use App\Exceptions\RateLimitExceededError;
use App\Services\RateLimiter;
use App\Services\SecurityService;
use App\Support\Settings;
use Closure;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;
use Symfony\Component\HttpFoundation\Response;

/**
 * معادل ApiRateLimitMiddleware در main.py: سقف کلی per-IP برای مسیرهای
 * غیرعمومی /api. خرابی خود محدودساز یعنی ۵۰۳، نه عبور بی‌صدا.
 */
class ApiRateLimitMiddleware
{
    public function __construct(
        private readonly Settings $settings,
        private readonly SecurityService $security,
    ) {
    }

    public function handle(Request $request, Closure $next): Response
    {
        $path = '/'.ltrim($request->path(), '/');
        if (! str_starts_with($path, '/api/') || str_starts_with($path, '/api/public/')) {
            return $next($request);
        }

        $clientIp = $this->security->extractClientIp($request);
        try {
            RateLimiter::checkAndIncrement(
                "api:ip:{$clientIp}",
                'api_request',
                (int) $this->settings->get('api_max_per_minute'),
                60,
            );
        } catch (RateLimitExceededError $e) {
            return response()->json($e->toArray(), 429, ['Retry-After' => (string) $e->retryAfterSeconds]);
        } catch (\Throwable $e) {
            Log::error('API rate limiter database failure: '.$e->getMessage());

            return response()->json([
                'ok' => false,
                'error' => [
                    'code' => 'RATE_LIMITER_UNAVAILABLE',
                    'message' => 'کنترل نرخ درخواست موقتاً در دسترس نیست.',
                    'details' => new \stdClass,
                ],
            ], 503);
        }

        return $next($request);
    }
}
