<?php

namespace Tests\Feature;

use Illuminate\Http\UploadedFile;

class RecordingFlowTest extends MasFeatureTestCase
{
    private function roomWithRunningTimer(array $auth): array
    {
        $room = $this->createRoom($auth, ['recording_enabled' => true]);
        $this->nameSpeaker($auth, $room['id'], $room['speakers'][0]['id'], 'سخنران اول');
        $this->authed($auth)->postJson("/api/rooms/{$room['id']}/timer/action", [
            'action' => 'start',
        ])->assertOk();

        return $room;
    }

    private function uploadChunk(array $auth, int $roomId, int $sessionId, int $seq, string $bytes)
    {
        return $this->authed($auth)->call(
            'POST',
            "/api/rooms/{$roomId}/recording/chunk",
            ['session_id' => $sessionId, 'seq' => $seq],
            [],
            ['chunk' => UploadedFile::fake()->createWithContent("chunk-{$seq}.webm", $bytes)],
        );
    }

    public function test_recording_start_requires_running_timer(): void
    {
        $auth = $this->registerUser();
        $room = $this->createRoom($auth, ['recording_enabled' => true]);

        $this->authed($auth)->postJson("/api/rooms/{$room['id']}/recording/start", [
            'mime_type' => 'audio/webm',
        ])->assertStatus(409)
            ->assertJsonPath('error.code', 'TIMER_NOT_RUNNING');
    }

    public function test_chunk_order_duplicate_and_finish_assembles_file(): void
    {
        $auth = $this->registerUser();
        $room = $this->roomWithRunningTimer($auth);
        $roomId = $room['id'];

        $start = $this->authed($auth)->postJson("/api/rooms/{$roomId}/recording/start", [
            'mime_type' => 'audio/webm',
        ]);
        $start->assertOk();
        $sessionId = $start->json('session_id');

        // ترتیب سخت‌گیرانه: seq=1 قبل از seq=0 رد می‌شود.
        $this->uploadChunk($auth, $roomId, $sessionId, 1, 'bbbb')
            ->assertStatus(400)
            ->assertJsonPath('error.code', 'RECORDING_ERROR');

        $this->uploadChunk($auth, $roomId, $sessionId, 0, 'aaaa')->assertOk();
        // ارسال تکراری همان seq بی‌اثر است (idempotent).
        $this->uploadChunk($auth, $roomId, $sessionId, 0, 'aaaa')->assertOk();
        $this->uploadChunk($auth, $roomId, $sessionId, 1, 'bbbb')->assertOk();

        $finish = $this->authed($auth)->postJson("/api/rooms/{$roomId}/recording/finish", [
            'save' => true,
        ]);
        $finish->assertOk();
        $this->assertNotNull($finish->json('file.id'));
        $this->assertSame(8, $finish->json('file.size_bytes'));

        $status = $this->authed($auth)->getJson("/api/rooms/{$roomId}/recording/status");
        $status->assertOk()->assertJsonPath('active', false);
    }

    public function test_play_supports_http_range(): void
    {
        $auth = $this->registerUser();
        $room = $this->roomWithRunningTimer($auth);
        $roomId = $room['id'];

        $start = $this->authed($auth)->postJson("/api/rooms/{$roomId}/recording/start", [
            'mime_type' => 'audio/webm',
        ]);
        $sessionId = $start->json('session_id');
        $payload = str_repeat('0123456789', 100); // ۱۰۰۰ بایت
        $this->uploadChunk($auth, $roomId, $sessionId, 0, $payload)->assertOk();
        $finish = $this->authed($auth)->postJson("/api/rooms/{$roomId}/recording/finish", [
            'save' => true,
        ]);
        $fileId = $finish->json('file.id');

        // رگرسیون B-04: پاسخ Range باید 206 و Content-Range درست داشته باشد.
        $response = $this->authed($auth)
            ->withHeader('Range', 'bytes=100-199')
            ->get("/api/rooms/{$roomId}/files/{$fileId}/play");
        $response->assertStatus(206);
        $this->assertSame('bytes 100-199/1000', $response->headers->get('Content-Range'));
        $this->assertSame('100', $response->headers->get('Content-Length'));
        $this->assertSame('bytes', $response->headers->get('Accept-Ranges'));
    }

    public function test_discard_removes_recording_without_file(): void
    {
        $auth = $this->registerUser();
        $room = $this->roomWithRunningTimer($auth);
        $roomId = $room['id'];

        $start = $this->authed($auth)->postJson("/api/rooms/{$roomId}/recording/start", [
            'mime_type' => 'audio/webm',
        ]);
        $sessionId = $start->json('session_id');
        $this->uploadChunk($auth, $roomId, $sessionId, 0, 'zzzz')->assertOk();

        $this->authed($auth)->postJson("/api/rooms/{$roomId}/recording/finish", [
            'save' => false,
        ])->assertOk();

        $detail = $this->authed($auth)->getJson("/api/rooms/{$roomId}")->json('room');
        $this->assertCount(0, $detail['recordings']);
    }
}
