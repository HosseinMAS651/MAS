<?php

namespace Tests\Feature;

use App\Models\User;

class AdminFlowTest extends MasFeatureTestCase
{
    public function test_admin_endpoints_require_admin_role(): void
    {
        $auth = $this->registerUser('plain-user');
        $this->authed($auth)->getJson('/api/admin/stats')
            ->assertForbidden()
            ->assertJsonPath('error.code', 'FORBIDDEN');
    }

    public function test_admin_stats_users_and_toggle_active(): void
    {
        $auth = $this->registerUser('the-admin');
        $other = $this->registerUser('regular-user');

        User::query()->where('id', $auth['user']['id'])->update(['role' => 'admin']);

        $this->authed($auth)->getJson('/api/admin/stats')
            ->assertOk()
            ->assertJsonPath('stats.users_count', 2);

        $users = $this->authed($auth)->getJson('/api/admin/users');
        $users->assertOk();
        $this->assertCount(2, $users->json('users'));

        // مدیر نمی‌تواند خودش را غیرفعال کند.
        $this->authed($auth)->postJson("/api/admin/users/{$auth['user']['id']}/toggle-active")
            ->assertStatus(400)
            ->assertJsonPath('error.code', 'VALIDATION_ERROR');

        $toggled = $this->authed($auth)->postJson("/api/admin/users/{$other['user']['id']}/toggle-active");
        $toggled->assertOk()->assertJsonPath('is_active', false);

        // کاربر غیرفعال‌شده دیگر وارد نمی‌شود.
        $this->anonymous()->postJson('/api/auth/login', [
            'username' => 'regular-user',
            'password' => 'password123',
        ])->assertUnauthorized();
    }

    public function test_admin_rooms_and_audit_logs_shapes(): void
    {
        $auth = $this->registerUser('admin-two');
        $room = $this->createRoom($auth);
        User::query()->where('id', $auth['user']['id'])->update(['role' => 'admin']);

        $rooms = $this->authed($auth)->getJson('/api/admin/rooms');
        $rooms->assertOk();
        $this->assertSame($room['id'], $rooms->json('rooms.0.id'));
        $this->assertSame('admin-two', $rooms->json('rooms.0.owner_username'));

        $logs = $this->authed($auth)->getJson('/api/admin/audit-logs');
        $logs->assertOk();
        $this->assertIsArray($logs->json('logs'));
    }
}
