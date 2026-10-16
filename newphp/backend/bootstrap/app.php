<?php

use App\Exceptions\AppError;
use App\Exceptions\RateLimitExceededError;
use App\Http\Middleware\ApiRateLimitMiddleware;
use App\Http\Middleware\AuthenticateMas;
use App\Http\Middleware\AuthenticateSpeakerDevice;
use App\Http\Middleware\EnsureAdmin;
use App\Http\Middleware\MasCsrfMiddleware;
use App\Http\Middleware\SecurityHeadersMiddleware;
use Illuminate\Database\Eloquent\ModelNotFoundException;
use Illuminate\Database\QueryException;
use Illuminate\Foundation\Application;
use Illuminate\Foundation\Configuration\Exceptions;
use Illuminate\Foundation\Configuration\Middleware;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;
use Illuminate\Validation\ValidationException;
use Symfony\Component\HttpKernel\Exception\HttpExceptionInterface;
use Symfony\Component\HttpKernel\Exception\NotFoundHttpException;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        web: __DIR__.'/../routes/web.php',
        api: __DIR__.'/../routes/api.php',
        commands: __DIR__.'/../routes/console.php',
        then: function (): void {
            // /health و /ready در ریشه‌اند (مثل FastAPI) ولی stateless مثل API.
            Route::middleware('api')->group(base_path('routes/health.php'));
        },
    )
    ->withMiddleware(function (Middleware $middleware): void {
        // PHP-FPM فقط پشت Nginx داخلی در دسترس است؛ هدرهای forwarded قابل اعتمادند.
        $middleware->trustProxies(at: '*');

        // ترتیب اجرا مثل main.py نسخهٔ Python (از بیرونی به درونی):
        // هدرهای امنیتی ← CSRF ← سقف نرخ کلی API ← مسیریاب.
        $middleware->append(SecurityHeadersMiddleware::class);
        $middleware->append(MasCsrfMiddleware::class);
        $middleware->append(ApiRateLimitMiddleware::class);

        $middleware->alias([
            'mas.auth' => AuthenticateMas::class,
            'mas.admin' => EnsureAdmin::class,
            'mas.speaker' => AuthenticateSpeakerDevice::class,
        ]);
    })
    ->withExceptions(function (Exceptions $exceptions): void {
        // خطاهای دامنه: همان envelope فارسی نسخهٔ Python.
        $exceptions->render(function (AppError $e, Request $request) {
            $response = response()->json($e->toArray(), $e->statusCode);
            if ($e instanceof RateLimitExceededError) {
                $response->headers->set('Retry-After', (string) $e->retryAfterSeconds);
            }

            return $response;
        });

        // خطاهای اعتبارسنجی فرم‌ها → ۴۰۰ VALIDATION_ERROR (نه ۴۲۲ پیش‌فرض Laravel).
        $exceptions->render(function (ValidationException $e, Request $request) {
            $errors = $e->errors();
            $firstField = $errors === [] ? null : array_key_first($errors);
            $firstMessage = $firstField !== null
                ? (string) ($errors[$firstField][0] ?? 'ورودی نامعتبر است.')
                : 'ورودی نامعتبر است.';
            $safeErrors = [];
            foreach ($errors as $field => $messages) {
                foreach ((array) $messages as $message) {
                    $safeErrors[] = [
                        'type' => 'validation_error',
                        'loc' => ['body', (string) $field],
                        'msg' => (string) $message,
                    ];
                }
            }

            return response()->json([
                'ok' => false,
                'error' => [
                    'code' => 'VALIDATION_ERROR',
                    'message' => "اطلاعات ارسالی نامعتبر است: {$firstMessage}",
                    'details' => [
                        'field' => $firstField !== null ? "body -> {$firstField}" : '',
                        'errors' => $safeErrors,
                    ],
                ],
            ], 400);
        });

        // خطاهای دیتابیس: تداخل یکتایی → ۴۰۹، قطعی اتصال → ۵۰۳، بقیه → ۵۰۰.
        $exceptions->render(function (QueryException $e, Request $request) {
            $sqlState = (string) $e->getCode();
            if (str_starts_with($sqlState, '23')) {
                return response()->json([
                    'ok' => false,
                    'error' => [
                        'code' => 'DATA_CONFLICT',
                        'message' => 'دادهٔ ارسالی با وضعیت فعلی سامانه تداخل دارد. لطفاً دوباره تلاش کنید.',
                        'details' => [],
                    ],
                ], 409);
            }
            if (str_starts_with($sqlState, '08')) {
                return response()->json([
                    'ok' => false,
                    'error' => [
                        'code' => 'DATABASE_UNAVAILABLE',
                        'message' => 'دیتابیس سامانه در دسترس نیست یا هنوز آماده نشده است. لطفاً چند لحظه بعد دوباره تلاش کنید.',
                        'details' => [],
                    ],
                ], 503);
            }

            return response()->json([
                'ok' => false,
                'error' => [
                    'code' => 'DATABASE_ERROR',
                    'message' => 'خطایی در پردازش دیتابیس رخ داد. لطفاً دوباره تلاش کنید.',
                    'details' => [],
                ],
            ], 500);
        });

        $exceptions->render(function (ModelNotFoundException $e, Request $request) {
            return response()->json([
                'ok' => false,
                'error' => [
                    'code' => 'HTTP_404',
                    'message' => 'صفحه یا منبع مورد نظر یافت نشد.',
                    'details' => [],
                ],
            ], 404);
        });

        $exceptions->render(function (NotFoundHttpException $e, Request $request) {
            return response()->json([
                'ok' => false,
                'error' => [
                    'code' => 'HTTP_404',
                    'message' => 'صفحه یا منبع مورد نظر یافت نشد.',
                    'details' => [],
                ],
            ], 404);
        });

        $exceptions->render(function (HttpExceptionInterface $e, Request $request) {
            $status = $e->getStatusCode();
            $message = $e->getMessage() !== '' ? $e->getMessage() : 'درخواست نامعتبر است.';
            if ($status === 404) {
                $message = 'صفحه یا منبع مورد نظر یافت نشد.';
            }

            return response()->json([
                'ok' => false,
                'error' => [
                    'code' => "HTTP_{$status}",
                    'message' => $message,
                    'details' => [],
                ],
            ], $status);
        });

        // هر خطای پیش‌بینی‌نشدهٔ دیگر → ۵۰۰ استاندارد (بدون افشای جزئیات داخلی).
        $exceptions->render(function (Throwable $e, Request $request) {
            return response()->json([
                'ok' => false,
                'error' => [
                    'code' => 'INTERNAL_SERVER_ERROR',
                    'message' => 'خطای داخلی سرور رخ داده است. لطفاً بعداً تلاش کنید.',
                    'details' => [],
                ],
            ], 500);
        });
    })->create();
