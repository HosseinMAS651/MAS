<?php

namespace App\Services;

use App\Exceptions\UnauthorizedError;
use App\Exceptions\ValidationAppError;
use App\Models\AuthSession;
use App\Models\User;
use App\Support\Mas;
use App\Support\Settings;
use Illuminate\Support\Facades\DB;

/** معادل mas_app/services/auth_service.py (ثبت‌نام، ورود، نشست، بازیابی). */
class AuthService
{
    private const RECOVERY_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';

    private const RECOVERY_CODE_LENGTH = 20;

    public function __construct(
        private readonly Settings $settings,
        private readonly SecurityService $security,
    ) {
    }

    public function settings(): Settings
    {
        return $this->settings;
    }

    public function register(
        string $username,
        string $password,
        string $accountName = '',
        ?int $age = null,
        string $job = '',
        string $timezone = 'Asia/Tehran',
        string $calendar = 'jalali',
        string $ip = '',
        string $userAgent = '',
    ): User {
        if ($ip !== '') {
            RateLimiter::checkAndIncrement(
                "register:ip:{$ip}",
                'register',
                (int) $this->settings->get('register_max_per_ip'),
                (int) $this->settings->get('register_window_seconds'),
            );
        }

        $userKey = Mas::usernameToKey($username);
        if ($userKey === '') {
            // رفع B-11: نام‌هایی مثل «___» نباید روی کلید خالی با هم برخورد کنند.
            throw new ValidationAppError('نام کاربری باید دست‌کم شامل یک حرف یا عدد باشد.');
        }
        if (User::query()->where('username_key', $userKey)->exists()) {
            throw new ValidationAppError('این نام کاربری قبلاً ثبت شده است.');
        }

        $now = Mas::nowMs();
        $user = new User([
            'username' => Mas::normalizeUsername($username),
            'username_key' => $userKey,
            'password_hash' => $this->security->hashPassword($password),
            'account_name' => Mas::normalizePersianText($accountName),
            'age' => $age,
            'job' => Mas::normalizePersianText($job),
            'role' => 'user', // ثبت‌نام عمومی هرگز مدیر نمی‌سازد؛ مدیر با دستور mas:create-admin ساخته می‌شود.
            'is_active' => true,
            'timezone' => $timezone !== '' ? $timezone : 'Asia/Tehran',
            'calendar' => $calendar !== '' ? $calendar : 'jalali',
            'storage_used_bytes' => 0,
            'failed_login_count' => 0,
            'locked_until_ms' => 0,
            'created_at_ms' => $now,
            'updated_at_ms' => $now,
            'last_login_at_ms' => $now,
            'version' => 1,
        ]);
        try {
            $user->save();
        } catch (\Illuminate\Database\UniqueConstraintViolationException) {
            throw new ValidationAppError('این نام کاربری قبلاً ثبت شده است.');
        }

        AuditLogger::log(
            'user_registered',
            actorUserId: $user->id,
            actorUsername: $user->username,
            targetType: 'user',
            targetId: (string) $user->id,
            detail: ['role' => 'user', 'username' => $user->username],
            ip: $ip,
            userAgent: $userAgent,
        );

        return $user;
    }

    /** صدور کد بازیابی انسانی؛ فقط هش HMAC آن ذخیره می‌شود و خود کد یک‌بار نمایش داده می‌شود. */
    public function issueRecoveryCode(
        User $user,
        ?string $currentPassword = null,
        string $ip = '',
        string $userAgent = '',
    ): string {
        if ($currentPassword !== null) {
            [$valid] = $this->security->verifyPassword($currentPassword, $user->password_hash);
            if (! $valid) {
                throw new ValidationAppError('رمز عبور فعلی نادرست است.');
            }
        }
        $alphabet = self::RECOVERY_CODE_ALPHABET;
        $raw = '';
        for ($i = 0; $i < self::RECOVERY_CODE_LENGTH; $i++) {
            $raw .= $alphabet[random_int(0, strlen($alphabet) - 1)];
        }
        $wasConfigured = ! empty($user->recovery_code_hash);
        $user->recovery_code_hash = $this->security->hashToken("recovery-code:{$raw}");
        $user->updated_at_ms = Mas::nowMs();
        $user->save();

        AuditLogger::log(
            'recovery_code_issued',
            actorUserId: $user->id,
            actorUsername: $user->username,
            severity: 'warning',
            targetType: 'user',
            targetId: (string) $user->id,
            detail: ['replaced_previous_code' => $wasConfigured],
            ip: $ip,
            userAgent: $userAgent,
        );

        return implode('-', str_split($raw, 5));
    }

    public function resetPasswordWithRecoveryCode(
        string $username,
        string $recoveryCode,
        string $newPassword,
        string $ip = '',
        string $userAgent = '',
    ): User {
        if ($ip !== '') {
            RateLimiter::checkAndIncrement(
                "recovery:ip:{$ip}",
                'password_recovery',
                (int) $this->settings->get('recovery_max_attempts'),
                (int) $this->settings->get('recovery_window_seconds'),
            );
        }

        $normalized = strtoupper(str_replace(['-', ' '], '', $recoveryCode));
        $validFormat = strlen($normalized) === self::RECOVERY_CODE_LENGTH
            && strspn($normalized, self::RECOVERY_CODE_ALPHABET) === self::RECOVERY_CODE_LENGTH;
        $candidate = $this->security->hashToken("recovery-code:{$normalized}");

        $user = User::query()->where('username_key', Mas::usernameToKey($username))->first();
        $expected = ($user && $user->recovery_code_hash)
            ? $user->recovery_code_hash
            : $this->security->hashToken('recovery-code:invalid-dummy-value');
        $matches = hash_equals($expected, $candidate);

        if (! $validFormat || ! $user || ! $user->is_active || ! $user->recovery_code_hash || ! $matches) {
            throw new UnauthorizedError('نام کاربری یا کد بازیابی معتبر نیست.');
        }

        $user->password_hash = $this->security->hashPassword($newPassword);
        $user->recovery_code_hash = null;
        $user->failed_login_count = 0;
        $user->locked_until_ms = 0;
        $user->updated_at_ms = Mas::nowMs();
        $user->save();
        AuthSession::query()->where('user_id', $user->id)->delete();
        if ($ip !== '') {
            RateLimiter::reset("recovery:ip:{$ip}");
        }

        AuditLogger::log(
            'password_recovered',
            actorUserId: $user->id,
            actorUsername: $user->username,
            severity: 'warning',
            targetType: 'user',
            targetId: (string) $user->id,
            detail: ['recovery_code_consumed' => true, 'sessions_invalidated' => true],
            ip: $ip,
            userAgent: $userAgent,
        );

        return $user;
    }

    /** @return array{0: User, 1: string, 2: string} (کاربر، توکن خام نشست، توکن خام CSRF) */
    public function login(string $username, string $password, string $ip = '', string $userAgent = ''): array
    {
        $userKey = Mas::usernameToKey($username);
        // محدودسازی هم بر اساس IP و هم ترکیب کاربر+IP است تا مهاجم نتواند از شبکهٔ
        // دیگری حساب واقعی کاربر را قفل کند.
        if ($ip !== '') {
            RateLimiter::checkAndIncrement(
                "login:ip:{$ip}", 'login',
                (int) $this->settings->get('login_max_attempts') * 3,
                (int) $this->settings->get('login_window_seconds'),
            );
            RateLimiter::checkAndIncrement(
                "login:userip:{$userKey}:{$ip}", 'login',
                (int) $this->settings->get('login_max_attempts'),
                (int) $this->settings->get('login_window_seconds'),
            );
        } else {
            RateLimiter::checkAndIncrement(
                "login:user:{$userKey}", 'login',
                (int) $this->settings->get('login_max_attempts'),
                (int) $this->settings->get('login_window_seconds'),
            );
        }

        $user = User::query()->where('username_key', $userKey)->first();
        $now = Mas::nowMs();
        if (! $user || ! $user->is_active) {
            throw new UnauthorizedError('نام کاربری یا رمز عبور اشتباه است.');
        }

        [$valid, $needsRehash] = $this->security->verifyPassword($password, $user->password_hash);
        if (! $valid) {
            $user->failed_login_count += 1;
            $user->updated_at_ms = $now;
            $user->save();
            AuditLogger::log(
                'login_failed',
                actorUserId: $user->id,
                actorUsername: $user->username,
                severity: 'warning',
                targetType: 'user',
                targetId: (string) $user->id,
                detail: ['reason' => 'invalid_password'],
                ip: $ip,
                userAgent: $userAgent,
            );
            throw new UnauthorizedError('نام کاربری یا رمز عبور اشتباه است.');
        }

        if ($needsRehash) {
            $user->password_hash = $this->security->hashPassword($password);
        }
        $user->failed_login_count = 0;
        $user->locked_until_ms = 0;
        $user->last_login_at_ms = $now;
        $user->updated_at_ms = $now;
        $user->save();

        if ($ip !== '') {
            RateLimiter::reset("login:ip:{$ip}");
            RateLimiter::reset("login:userip:{$userKey}:{$ip}");
        } else {
            RateLimiter::reset("login:user:{$userKey}");
        }

        $rawSessionToken = $this->security->generateSessionToken();
        $rawCsrfToken = $this->security->generateCsrfToken();

        AuthSession::create([
            'user_id' => $user->id,
            'token_hash' => $this->security->hashToken($rawSessionToken),
            'csrf_hash' => $this->security->hashToken($rawCsrfToken),
            'created_at_ms' => $now,
            'expires_at_ms' => $now + $this->settings->sessionIdleSeconds() * 1000,
            'last_seen_at_ms' => $now,
            'ip' => mb_substr($ip, 0, 64),
            'user_agent' => mb_substr($userAgent, 0, 255),
        ]);

        AuditLogger::log(
            'login_success',
            actorUserId: $user->id,
            actorUsername: $user->username,
            targetType: 'user',
            targetId: (string) $user->id,
            detail: ['upgraded_hash' => $needsRehash],
            ip: $ip,
            userAgent: $userAgent,
        );

        return [$user, $rawSessionToken, $rawCsrfToken];
    }

    /** @return array{0: User, 1: AuthSession} */
    public function getUserFromToken(string $rawToken, bool $touch = true): array
    {
        if ($rawToken === '') {
            throw new UnauthorizedError('توکن نشست ارائه نشده است.');
        }
        $session = AuthSession::query()
            ->where('token_hash', $this->security->hashToken($rawToken))
            ->first();
        if (! $session) {
            throw new UnauthorizedError('نشست نامعتبر است یا منقضی شده است.');
        }

        $now = Mas::nowMs();
        if ($session->expires_at_ms < $now) {
            $session->delete();
            throw new UnauthorizedError('نشست شما به دلیل عدم فعالیت منقضی شده است.');
        }
        if (($now - $session->created_at_ms) > $this->settings->sessionAbsoluteSeconds() * 1000) {
            $session->delete();
            throw new UnauthorizedError('نشست شما به حداکثر طول مجاز رسیده است. لطفاً دوباره وارد شوید.');
        }

        $user = User::query()->find($session->user_id);
        if (! $user || ! $user->is_active) {
            $session->delete();
            throw new UnauthorizedError('حساب کاربری فعال نیست.');
        }

        if ($touch) {
            $session->last_seen_at_ms = $now;
            $session->expires_at_ms = $now + $this->settings->sessionIdleSeconds() * 1000;
            $session->save();
        }

        return [$user, $session];
    }

    public function logout(string $rawToken): void
    {
        if ($rawToken === '') {
            return;
        }
        AuthSession::query()
            ->where('token_hash', $this->security->hashToken($rawToken))
            ->delete();
    }

    public function changePassword(
        User $user,
        string $currentPassword,
        string $newPassword,
        string $currentSessionToken = '',
        string $ip = '',
        string $userAgent = '',
    ): void {
        [$valid] = $this->security->verifyPassword($currentPassword, $user->password_hash);
        if (! $valid) {
            throw new ValidationAppError('رمز عبور فعلی نادرست است.');
        }
        if ($currentPassword === $newPassword) {
            throw new ValidationAppError('رمز عبور جدید نمی‌تواند با رمز عبور فعلی یکسان باشد.');
        }

        $user->password_hash = $this->security->hashPassword($newPassword);
        $user->updated_at_ms = Mas::nowMs();
        $user->save();

        $query = AuthSession::query()->where('user_id', $user->id);
        if ($currentSessionToken !== '') {
            $query->where('token_hash', '!=', $this->security->hashToken($currentSessionToken));
        }
        $query->delete();

        AuditLogger::log(
            'password_changed',
            actorUserId: $user->id,
            actorUsername: $user->username,
            severity: 'warning',
            targetType: 'user',
            targetId: (string) $user->id,
            detail: ['sessions_invalidated' => true],
            ip: $ip,
            userAgent: $userAgent,
        );
    }

    public function updateProfile(
        User $user,
        string $accountName,
        ?int $age,
        string $job,
        string $timezone,
        string $calendar,
    ): User {
        $user->account_name = Mas::normalizePersianText($accountName);
        $user->age = $age;
        $user->job = Mas::normalizePersianText($job);
        if ($timezone !== '') {
            $user->timezone = $timezone;
        }
        if (in_array($calendar, ['jalali', 'gregorian'], true)) {
            $user->calendar = $calendar;
        }
        $user->profile_completed = true;
        $user->updated_at_ms = Mas::nowMs();
        $user->save();

        return $user;
    }
}
