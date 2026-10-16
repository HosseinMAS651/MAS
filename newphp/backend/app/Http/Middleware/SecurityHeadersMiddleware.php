<?php

namespace App\Http\Middleware;

use App\Support\Settings;
use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/**
 * معادل SecurityHeadersMiddleware در main.py: هدرهای امنیتی همهٔ پاسخ‌ها،
 * CSP سخت‌گیرانه و استثنای sandbox برای پیش‌نمایش فایل عمومی.
 */
class SecurityHeadersMiddleware
{
    public function __construct(private readonly Settings $settings)
    {
    }

    public function handle(Request $request, Closure $next): Response
    {
        $response = $next($request);
        $path = '/'.ltrim($request->path(), '/');
        $publicFileFrame = (bool) preg_match('#^/api/public/[^/]+/files/[^/]+$#', $path);

        $response->headers->set('X-Content-Type-Options', 'nosniff');
        $response->headers->set('X-Frame-Options', $publicFileFrame ? 'SAMEORIGIN' : 'DENY');
        $response->headers->set('X-XSS-Protection', '1; mode=block');
        $response->headers->set('Referrer-Policy', 'strict-origin-when-cross-origin');
        $response->headers->set('Permissions-Policy', 'microphone=(self), camera=(), geolocation=()');

        if ($publicFileFrame) {
            $csp = "default-src 'none'; img-src 'self' data: blob:; media-src 'self' blob:; "
                ."style-src 'unsafe-inline'; frame-ancestors 'self'; sandbox";
        } else {
            $csp = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                ."img-src 'self' data: blob: https:; media-src 'self' blob: https:; "
                ."connect-src 'self' blob: https:; font-src 'self' data:; frame-ancestors 'none';";
        }
        $response->headers->set('Content-Security-Policy', $csp);

        if ($this->settings->isProduction() && $this->settings->get('cookie_secure')) {
            $response->headers->set('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
        }

        $response->headers->remove('Server');
        $response->headers->remove('X-Powered-By');

        $contentType = strtolower((string) $response->headers->get('content-type', ''));
        if (str_starts_with($contentType, 'text/html')) {
            $response->headers->set(
                'Cache-Control',
                'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0, s-maxage=0',
            );
            $response->headers->set('Pragma', 'no-cache');
            $response->headers->set('Expires', '0');
        } elseif (str_starts_with($path, '/assets/')) {
            $response->headers->set('Cache-Control', 'public, max-age=31536000, immutable');
        }

        return $response;
    }
}
