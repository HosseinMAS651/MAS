<?php

namespace Tests\Feature;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Testing\TestResponse;
use Tests\TestCase;

/**
 * پایهٔ تست‌های قراردادی API: ساخت کاربر از مسیر واقعی ثبت‌نام و نگهداری
 * کوکی نشست + توکن CSRF، دقیقاً مثل مرورگر فرانت‌اند React.
 */
abstract class MasFeatureTestCase extends TestCase
{
    use RefreshDatabase;

    /** @return array{session: string, csrf: string, user: array<string, mixed>} */
    protected function registerUser(string $username = 'owner', string $password = 'password123'): array
    {
        $response = $this->postJson('/api/auth/register', [
            'username' => $username,
            'password' => $password,
            'account_name' => 'کاربر تست',
        ]);
        $response->assertOk()->assertJsonPath('ok', true);

        return $this->authFromResponse($response);
    }

    /** @return array{session: string, csrf: string, user: array<string, mixed>} */
    protected function authFromResponse(TestResponse $response): array
    {
        $cookies = [];
        foreach ($response->headers->getCookies() as $cookie) {
            $cookies[$cookie->getName()] = $cookie->getValue();
        }

        return [
            'session' => $cookies['mas_session'] ?? '',
            'csrf' => $cookies['mas_csrf'] ?? '',
            'user' => $response->json('user') ?? [],
        ];
    }

    /** ادامهٔ زنجیرهٔ تست با احراز کوکی + هدر CSRF (مثل مرورگر). */
    protected function authed(array $auth): static
    {
        return $this
            ->withCookie('mas_session', $auth['session'])
            ->withHeader('X-CSRF-Token', $auth['csrf']);
    }

    /** پاک‌کردن کوکی‌های پیش‌فرض تست برای صدا زدن endpointهای عمومی. */
    protected function anonymous(): static
    {
        return $this->withCookies([]);
    }

    /** ساخت اتاق از API و برگرداندن پاسخ جزئیات (شامل public_token و سخنران‌ها). */
    protected function createRoom(array $auth, array $overrides = []): array
    {
        $payload = array_merge([
            'name' => 'اتاق تست',
            'capacity' => 2,
            'description' => '',
            'recording_enabled' => true,
            'live_files_enabled' => true,
            'public_enabled' => true,
        ], $overrides);

        $created = $this->authed($auth)->postJson('/api/rooms', $payload);
        $created->assertOk()->assertJsonPath('ok', true);
        $roomId = $created->json('room.id');

        $detail = $this->authed($auth)->getJson("/api/rooms/{$roomId}");
        $detail->assertOk();

        return $detail->json('room');
    }

    /** نام‌گذاری اسلات سخنران از مسیر ویرایش مالک. */
    protected function nameSpeaker(array $auth, int $roomId, int $speakerId, string $name): void
    {
        $this->authed($auth)->putJson("/api/rooms/{$roomId}/speakers/{$speakerId}", [
            'name' => $name,
            'gender' => '',
            'description' => '',
        ])->assertOk();
    }
}
