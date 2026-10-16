<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\ChangePasswordRequest;
use App\Http\Requests\IssueRecoveryCodeRequest;
use App\Http\Requests\LoginRequest;
use App\Http\Requests\RecoverPasswordRequest;
use App\Http\Requests\RegisterRequest;
use App\Http\Requests\UpdateProfileRequest;
use App\Presenters\MasPresenter;
use App\Services\AuthService;
use App\Services\SecurityService;
use App\Support\Settings;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Cookie;

/** معادل mas_app/api/routers/auth.py */
class AuthController extends Controller
{
    public function __construct(
        private readonly AuthService $authService,
        private readonly SecurityService $security,
        private readonly Settings $settings,
    ) {
    }

    private function clientIp(Request $request): string
    {
        return $this->security->extractClientIp($request);
    }

    private function sessionCookies(JsonResponse $response, string $sessionToken, string $csrfToken): JsonResponse
    {
        $minutes = intdiv($this->settings->sessionIdleSeconds(), 60);
        $secure = (bool) $this->settings->get('cookie_secure');
        $sameSite = (string) $this->settings->get('cookie_samesite', 'lax');
        $domain = (string) $this->settings->get('cookie_domain', '');

        $response->headers->setCookie(new Cookie(
            (string) $this->settings->get('cookie_name', 'mas_session'),
            $sessionToken, time() + $minutes * 60, '/', $domain !== '' ? $domain : null,
            $secure, true, false, $sameSite,
        ));
        $response->headers->setCookie(new Cookie(
            (string) $this->settings->get('csrf_cookie_name', 'mas_csrf'),
            $csrfToken, time() + $minutes * 60, '/', $domain !== '' ? $domain : null,
            $secure, false, false, $sameSite,
        ));

        return $response;
    }

    public function register(RegisterRequest $request): JsonResponse
    {
        $data = $request->validated();
        $ip = $this->clientIp($request);
        $userAgent = (string) $request->userAgent();

        $user = $this->authService->register(
            username: $data['username'],
            password: $data['password'],
            accountName: $data['account_name'] ?? '',
            age: $data['age'] ?? null,
            job: $data['job'] ?? '',
            timezone: $data['timezone'] ?? 'Asia/Tehran',
            calendar: $data['calendar'] ?? 'jalali',
            ip: $ip,
            userAgent: $userAgent,
        );
        // کد بازیابی فقط یک‌بار در پاسخ ثبت‌نام نمایش داده می‌شود؛ فقط هش آن در DB می‌ماند.
        $recoveryCode = $this->authService->issueRecoveryCode($user, ip: $ip, userAgent: $userAgent);
        // ورود خودکار بلافاصله پس از ثبت‌نام
        [, $sessionToken, $csrfToken] = $this->authService->login(
            $data['username'], $data['password'], $ip, $userAgent,
        );

        $response = response()->json([
            'ok' => true,
            'user' => MasPresenter::user($user),
            'recovery_code' => $recoveryCode,
        ]);

        return $this->sessionCookies($response, $sessionToken, $csrfToken);
    }

    public function login(LoginRequest $request): JsonResponse
    {
        $data = $request->validated();
        [$user, $sessionToken, $csrfToken] = $this->authService->login(
            $data['username'],
            $data['password'],
            $this->clientIp($request),
            (string) $request->userAgent(),
        );

        $response = response()->json([
            'ok' => true,
            'user' => MasPresenter::user($user),
        ]);

        return $this->sessionCookies($response, $sessionToken, $csrfToken);
    }

    public function logout(Request $request): JsonResponse
    {
        $token = $request->cookie((string) $this->settings->get('cookie_name', 'mas_session'));
        if ($token) {
            $this->authService->logout((string) $token);
        }
        $domain = (string) $this->settings->get('cookie_domain', '');
        $response = response()->json(['ok' => true, 'message' => 'خروج با موفقیت انجام شد.']);
        foreach (['cookie_name', 'csrf_cookie_name'] as $key) {
            $response->headers->setCookie(new Cookie(
                (string) $this->settings->get($key),
                '', time() - 3600, '/', $domain !== '' ? $domain : null,
            ));
        }

        return $response;
    }

    public function me(Request $request): JsonResponse
    {
        return response()->json([
            'ok' => true,
            'user' => MasPresenter::user($request->attributes->get('mas_user')),
        ]);
    }

    public function profile(UpdateProfileRequest $request): JsonResponse
    {
        $data = $request->validated();
        $user = $this->authService->updateProfile(
            $request->attributes->get('mas_user'),
            accountName: $data['account_name'] ?? '',
            age: $data['age'] ?? null,
            job: $data['job'] ?? '',
            timezone: $data['timezone'] ?? '',
            calendar: $data['calendar'] ?? '',
        );

        return response()->json(['ok' => true, 'user' => MasPresenter::user($user)]);
    }

    public function changePassword(ChangePasswordRequest $request): JsonResponse
    {
        $data = $request->validated();
        $token = (string) $request->cookie((string) $this->settings->get('cookie_name', 'mas_session'), '');
        $this->authService->changePassword(
            $request->attributes->get('mas_user'),
            currentPassword: $data['current_password'],
            newPassword: $data['new_password'],
            currentSessionToken: $token,
            ip: $this->clientIp($request),
            userAgent: (string) $request->userAgent(),
        );

        return response()->json(['ok' => true, 'message' => 'رمز عبور با موفقیت تغییر یافت.']);
    }

    public function recoveryCode(IssueRecoveryCodeRequest $request): JsonResponse
    {
        $code = $this->authService->issueRecoveryCode(
            $request->attributes->get('mas_user'),
            currentPassword: $request->validated()['current_password'],
            ip: $this->clientIp($request),
            userAgent: (string) $request->userAgent(),
        );

        return response()->json(['ok' => true, 'recovery_code' => $code]);
    }

    public function recoverPassword(RecoverPasswordRequest $request): JsonResponse
    {
        $data = $request->validated();
        $this->authService->resetPasswordWithRecoveryCode(
            username: $data['username'],
            recoveryCode: $data['recovery_code'],
            newPassword: $data['new_password'],
            ip: $this->clientIp($request),
            userAgent: (string) $request->userAgent(),
        );

        return response()->json([
            'ok' => true,
            'message' => 'رمز عبور با موفقیت بازنشانی شد. اکنون وارد شوید.',
        ]);
    }
}
