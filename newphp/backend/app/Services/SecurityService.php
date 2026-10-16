<?php

namespace App\Services;

use App\Support\Settings;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Crypt;
use Illuminate\Support\Facades\Hash;

/**
 * معادل mas_app/core/security.py (SecurityManager): هش Argon2id رمزها،
 * هش HMAC توکن‌ها برای ذخیره‌سازی، رمزگذاری کد سخنران و استخراج امن IP.
 */
class SecurityService
{
    private const PBKDF2_PREFIX = 'pbkdf2_sha256';

    public function __construct(private readonly Settings $settings)
    {
    }

    public function settings(): Settings
    {
        return $this->settings;
    }

    // ── رمز عبور ──────────────────────────────────────────────
    public function hashPassword(string $password): string
    {
        return Hash::make($password); // درایور پیش‌فرض در config/hashing.php روی argon2id است.
    }

    /**
     * @return array{0: bool, 1: bool} (معتبر است؟، نیاز به rehash دارد؟)
     *         هش‌های قدیمی pbkdf2_sha256 نسخهٔ Python هم پشتیبانی می‌شوند تا
     *         در صورت import دیتابیس قدیمی، حساب‌ها قفل نشوند؛ بعد از اولین
     *         ورود موفق به Argon2id ارتقا می‌یابند.
     */
    public function verifyPassword(string $password, string $encodedHash): array
    {
        if ($encodedHash === '' || $password === '') {
            return [false, false];
        }
        if (str_starts_with($encodedHash, self::PBKDF2_PREFIX)) {
            $valid = $this->verifyPbkdf2($password, $encodedHash);

            return [$valid, $valid];
        }
        if (! Hash::check($password, $encodedHash)) {
            return [false, false];
        }

        return [true, Hash::needsRehash($encodedHash)];
    }

    private function verifyPbkdf2(string $password, string $encoded): bool
    {
        $parts = explode('$', $encoded);
        if (count($parts) !== 4 || $parts[0] !== self::PBKDF2_PREFIX) {
            return false;
        }
        $rounds = (int) $parts[1];
        $salt = hex2bin($parts[2]);
        if ($salt === false || $rounds <= 0) {
            return false;
        }
        $candidate = hash_pbkdf2('sha256', $password, $salt, $rounds);

        return hash_equals($parts[3], $candidate);
    }

    // ── توکن‌ها ───────────────────────────────────────────────
    /** توکن خام نشست (فقط در کوکی/Header می‌رود؛ در DB هش آن ذخیره می‌شود). */
    public function generateSessionToken(): string
    {
        return $this->urlsafeToken(32);
    }

    public function generateCsrfToken(): string
    {
        return $this->urlsafeToken(32);
    }

    /** توکن تصادفی ۴۳ کاراکتری لینک عمومی اتاق. */
    public function generatePublicToken(): string
    {
        return $this->urlsafeToken(32);
    }

    private function urlsafeToken(int $bytes): string
    {
        return rtrim(strtr(base64_encode(random_bytes($bytes)), '+/', '-_'), '=');
    }

    /** هش HMAC توکن برای ذخیره‌سازی؛ نشت DB به‌تنهایی توکن‌ها را افشا نمی‌کند. */
    public function hashToken(string $token): string
    {
        return hash_hmac('sha256', $token, $this->settings->secretKey());
    }

    public function verifyCsrf(string $rawToken, string $expectedHash): bool
    {
        if ($rawToken === '' || $expectedHash === '') {
            return false;
        }

        return hash_equals($expectedHash, $this->hashToken($rawToken));
    }

    // ── رمزگذاری راز کوتاه (کد سخنران) ───────────────────────
    public function encryptSecret(string $value): string
    {
        return Crypt::encryptString($value);
    }

    public function decryptSecret(string $encrypted): string
    {
        try {
            return Crypt::decryptString($encrypted);
        } catch (\Throwable $e) {
            throw new \RuntimeException(
                'The stored secret cannot be decrypted with the current APP_KEY; '
                .'keep that key stable or rotate the affected secret.',
                previous: $e,
            );
        }
    }

    // ── استخراج IP کلاینت (رفع BE-01/BE-01b نسخهٔ Python) ────
    /**
     * بر اساس MAS_TRUSTED_PROXY_HOPS: وقتی N پروکسی معتبر جلوی برنامه است،
     * آی‌پی N خانه مانده از انتهای X-Forwarded-For کلاینت واقعی است.
     */
    public function extractClientIp(Request $request): string
    {
        $peer = trim((string) ($request->server('REMOTE_ADDR') ?? ''));
        $hops = (int) $this->settings->get('trusted_proxy_hops', 1);
        if ($hops <= 0) {
            return $peer !== '' ? $peer : '127.0.0.1';
        }
        $xff = $request->headers->get('x-forwarded-for');
        if (! $xff) {
            return $peer !== '' ? $peer : '127.0.0.1';
        }
        $parts = array_values(array_filter(array_map('trim', explode(',', $xff)), fn ($p) => $p !== ''));
        if ($parts === []) {
            return $peer !== '' ? $peer : '127.0.0.1';
        }
        $candidate = count($parts) > $hops ? $parts[count($parts) - $hops - 1] : $parts[0];
        $clean = preg_replace('/[^0-9a-fA-F:.]/', '', $candidate) ?? '';

        return $clean !== '' ? $clean : ($peer !== '' ? $peer : '127.0.0.1');
    }
}
