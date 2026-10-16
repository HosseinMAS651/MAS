<?php

namespace Tests\Feature;

class PublicSpeakerFlowTest extends MasFeatureTestCase
{
    /** @return array{0: array, 1: array, 2: string} (auth مالک، جزئیات اتاق، توکن عمومی) */
    private function speakerModeRoom(): array
    {
        $auth = $this->registerUser();
        $room = $this->createRoom($auth, [
            'recording_enabled' => false,
            'speaker_mode_enabled' => true,
            'speaker_uploads_enabled' => true,
            'public_enabled' => true,
        ]);
        $this->nameSpeaker($auth, $room['id'], $room['speakers'][0]['id'], 'سخنران اصلی');

        $detail = $this->authed($auth)->getJson("/api/rooms/{$room['id']}")->json('room');

        return [$auth, $detail, $detail['public_token']];
    }

    public function test_public_state_etag_and_unknown_token(): void
    {
        [, , $token] = $this->speakerModeRoom();

        $first = $this->anonymous()->getJson("/api/public/{$token}/state");
        $first->assertOk()
            ->assertJsonPath('state.room_name', 'اتاق تست')
            ->assertJsonPath('state.speaker_mode_enabled', true);
        $etag = $first->headers->get('ETag');
        $this->assertNotEmpty($etag);

        $this->anonymous()
            ->withHeader('If-None-Match', $etag)
            ->getJson("/api/public/{$token}/state")
            ->assertStatus(304);

        $this->anonymous()->getJson('/api/public/not-a-real-token/state')
            ->assertNotFound()
            ->assertJsonPath('error.code', 'NOT_FOUND');
    }

    public function test_speaker_enter_heartbeat_and_leave(): void
    {
        [, $room, $token] = $this->speakerModeRoom();
        $code = $room['speakers'][0]['speaker_code'];
        $this->assertNotEmpty($code);

        // کد اشتباه → ۴۰۱
        $this->anonymous()->postJson("/api/public/{$token}/speaker/enter", ['code' => 'ZZZZ'])
            ->assertUnauthorized()
            ->assertJsonPath('error.code', 'UNAUTHORIZED');

        $enter = $this->anonymous()->postJson("/api/public/{$token}/speaker/enter", ['code' => $code]);
        $enter->assertOk()
            ->assertJsonPath('speaker.name', 'سخنران اصلی')
            ->assertJsonPath('speaker_uploads_enabled', true);
        $deviceToken = $enter->json('session_token');
        $this->assertNotEmpty($deviceToken);

        // بدون توکن دستگاه → ۴۰۱
        $this->anonymous()->postJson("/api/public/{$token}/speaker/heartbeat", [
            'microphone_ready' => true,
        ])->assertUnauthorized();

        $this->anonymous()
            ->withHeader('Authorization', "Bearer {$deviceToken}")
            ->postJson("/api/public/{$token}/speaker/heartbeat", ['microphone_ready' => true])
            ->assertOk()
            ->assertJsonPath('presence_status', 'ready');

        $this->anonymous()
            ->withHeader('Authorization', "Bearer {$deviceToken}")
            ->postJson("/api/public/{$token}/speaker/leave")
            ->assertOk();

        // بعد از leave همان توکن دیگر معتبر نیست.
        $this->anonymous()
            ->withHeader('Authorization', "Bearer {$deviceToken}")
            ->postJson("/api/public/{$token}/speaker/heartbeat", ['microphone_ready' => true])
            ->assertUnauthorized();
    }

    public function test_reactions_flow_and_owner_toggle(): void
    {
        [$auth, $room, $token] = $this->speakerModeRoom();

        $this->anonymous()->postJson("/api/public/{$token}/reactions", ['emoji' => 'heart'])
            ->assertOk()
            ->assertJsonPath('ok', true);

        $recent = $this->anonymous()->getJson("/api/public/{$token}/reactions");
        $recent->assertOk()->assertJsonPath('reactions_enabled', true);
        $this->assertSame(1, $recent->json('totals.heart') ?? $recent->json('totals')['heart'] ?? 0);

        // خاموش‌کردن واکنش‌ها توسط مالک، ارسال بعدی را ۴۰۳ می‌کند.
        $this->authed($auth)->postJson("/api/rooms/{$room['id']}/reactions/toggle")
            ->assertOk()
            ->assertJsonPath('reactions_enabled', false);

        $this->anonymous()->postJson("/api/public/{$token}/reactions", ['emoji' => 'heart'])
            ->assertForbidden()
            ->assertJsonPath('error.code', 'FORBIDDEN');
    }
}
