<?php

namespace Tests\Feature;

class AuthFlowTest extends MasFeatureTestCase
{
    public function test_register_issues_recovery_code_and_auto_logs_in(): void
    {
        $response = $this->postJson('/api/auth/register', [
            'username' => 'alice',
            'password' => 'password123',
            'account_name' => 'آلیس',
        ]);
        $response->assertOk()
            ->assertJsonPath('ok', true)
            ->assertJsonPath('user.username', 'alice')
            ->assertJsonPath('user.role', 'user');
        $this->assertNotEmpty($response->json('recovery_code'));

        $auth = $this->authFromResponse($response);
        $this->assertNotSame('', $auth['session']);
        $this->assertNotSame('', $auth['csrf']);

        $this->authed($auth)->getJson('/api/auth/me')
            ->assertOk()
            ->assertJsonPath('user.username', 'alice');
    }

    public function test_register_rejects_username_that_collapses_to_empty_key(): void
    {
        // رگرسیون B-11: نام‌هایی مثل «___» نباید روی کلید خالی ذخیره شوند.
        $this->postJson('/api/auth/register', [
            'username' => '___',
            'password' => 'password123',
        ])->assertStatus(400)
            ->assertJsonPath('error.code', 'VALIDATION_ERROR');
    }

    public function test_duplicate_username_is_rejected(): void
    {
        $this->registerUser('bob');
        $this->anonymous()->postJson('/api/auth/register', [
            'username' => 'bob',
            'password' => 'password123',
        ])->assertStatus(400)
            ->assertJsonPath('error.code', 'VALIDATION_ERROR');
    }

    public function test_login_wrong_password_and_csrf_guard(): void
    {
        $this->registerUser('carol');

        $this->anonymous()->postJson('/api/auth/login', [
            'username' => 'carol',
            'password' => 'wrong-password',
        ])->assertUnauthorized()
            ->assertJsonPath('error.code', 'UNAUTHORIZED');

        $login = $this->anonymous()->postJson('/api/auth/login', [
            'username' => 'carol',
            'password' => 'password123',
        ]);
        $login->assertOk();
        $auth = $this->authFromResponse($login);

        // بدون هدر CSRF درخواست state-changing کوکی‌محور رد می‌شود.
        $this->withCookie('mas_session', $auth['session'])
            ->postJson('/api/rooms', ['name' => 'x', 'capacity' => 1])
            ->assertForbidden()
            ->assertJsonPath('error.code', 'CSRF_TOKEN_MISSING');

        // با هدر اشتباه هم رد می‌شود.
        $this->withCookie('mas_session', $auth['session'])
            ->withHeader('X-CSRF-Token', 'not-the-token')
            ->postJson('/api/rooms', ['name' => 'x', 'capacity' => 1])
            ->assertForbidden()
            ->assertJsonPath('error.code', 'CSRF_TOKEN_INVALID');

        // و با توکن درست انجام می‌شود.
        $this->authed($auth)
            ->postJson('/api/rooms', ['name' => 'اتاق کارول', 'capacity' => 1])
            ->assertOk();
    }

    public function test_bearer_token_is_csrf_exempt(): void
    {
        $auth = $this->registerUser('dave');
        $this->anonymous()
            ->withHeader('Authorization', 'Bearer '.$auth['session'])
            ->postJson('/api/rooms', ['name' => 'اتاق دیو', 'capacity' => 1])
            ->assertOk();
    }

    public function test_logout_invalidates_session(): void
    {
        $auth = $this->registerUser('erin');
        $this->authed($auth)->postJson('/api/auth/logout')->assertOk();
        $this->authed($auth)->getJson('/api/auth/me')->assertUnauthorized();
    }

    public function test_recover_password_with_recovery_code(): void
    {
        $register = $this->postJson('/api/auth/register', [
            'username' => 'frank',
            'password' => 'password123',
        ]);
        $code = $register->json('recovery_code');

        $this->anonymous()->postJson('/api/auth/recover-password', [
            'username' => 'frank',
            'recovery_code' => $code,
            'new_password' => 'newpassword456',
        ])->assertOk();

        $this->anonymous()->postJson('/api/auth/login', [
            'username' => 'frank',
            'password' => 'newpassword456',
        ])->assertOk();
    }

    public function test_me_requires_authentication(): void
    {
        $this->anonymous()->getJson('/api/auth/me')
            ->assertUnauthorized()
            ->assertJsonPath('ok', false)
            ->assertJsonPath('error.code', 'UNAUTHORIZED');
    }
}
