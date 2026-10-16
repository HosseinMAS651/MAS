<?php

namespace Tests\Feature;

class TimerFlowTest extends MasFeatureTestCase
{
    public function test_timer_state_etag_returns_304_when_unchanged(): void
    {
        $auth = $this->registerUser();
        $room = $this->createRoom($auth);
        $this->nameSpeaker($auth, $room['id'], $room['speakers'][0]['id'], 'سخنران اول');

        $first = $this->authed($auth)->getJson("/api/rooms/{$room['id']}/timer/state");
        $first->assertOk()->assertJsonPath('state.running', false);
        $etag = $first->headers->get('ETag');
        $this->assertNotEmpty($etag);

        $this->authed($auth)
            ->withHeader('If-None-Match', $etag)
            ->getJson("/api/rooms/{$room['id']}/timer/state")
            ->assertStatus(304);
    }

    public function test_timer_actions_and_version_conflict(): void
    {
        $auth = $this->registerUser();
        $room = $this->createRoom($auth);
        $roomId = $room['id'];
        $this->nameSpeaker($auth, $roomId, $room['speakers'][0]['id'], 'سخنران اول');

        $started = $this->authed($auth)->postJson("/api/rooms/{$roomId}/timer/action", [
            'action' => 'start',
        ]);
        $started->assertOk()->assertJsonPath('state.running', true);
        $version = $started->json('state.version');

        // نسخهٔ کهنه → تداخل وضعیت (STATE_VERSION_CONFLICT).
        $this->authed($auth)->postJson("/api/rooms/{$roomId}/timer/action", [
            'action' => 'pause',
            'expected_version' => $version + 100,
        ])->assertStatus(409)
            ->assertJsonPath('error.code', 'STATE_VERSION_CONFLICT');

        // شروع دوباره هنگام اجرا ممکن نیست.
        $this->authed($auth)->postJson("/api/rooms/{$roomId}/timer/action", [
            'action' => 'start',
        ])->assertStatus(409)
            ->assertJsonPath('error.code', 'TIMER_ALREADY_RUNNING');

        $this->authed($auth)->postJson("/api/rooms/{$roomId}/timer/action", [
            'action' => 'pause',
            'expected_version' => $version,
        ])->assertOk()->assertJsonPath('state.running', false);
    }
}
