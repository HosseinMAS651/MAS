<?php

namespace Tests\Feature;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class HealthTest extends TestCase
{
    use RefreshDatabase;

    public function test_health_returns_version(): void
    {
        $this->getJson('/health')
            ->assertOk()
            ->assertExactJson(['ok' => true, 'version' => '2.0.0']);
    }

    public function test_ready_reports_database_and_storage(): void
    {
        $this->getJson('/ready')
            ->assertOk()
            ->assertJsonPath('ok', true)
            ->assertJsonPath('db', true)
            ->assertJsonPath('storage', true)
            ->assertJsonPath('storage_backend', 'local');
    }

    public function test_unknown_route_uses_error_envelope(): void
    {
        $this->getJson('/api/rooms/999999/timer/state')
            ->assertUnauthorized()
            ->assertJsonPath('ok', false)
            ->assertJsonPath('error.code', 'UNAUTHORIZED');
    }
}
