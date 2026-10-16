<?php

namespace Tests\Feature;

use App\Models\SpeechFile;
use Illuminate\Http\UploadedFile;

class RoomValidationTest extends MasFeatureTestCase
{
    public function test_blank_room_name_is_rejected(): void
    {
        $auth = $this->registerUser();
        // رگرسیون B-05: نام فقط‌فاصله نباید پذیرفته شود.
        $this->authed($auth)->postJson('/api/rooms', [
            'name' => '   ',
            'capacity' => 2,
        ])->assertStatus(400)
            ->assertJsonPath('error.code', 'VALIDATION_ERROR');
    }

    public function test_capacity_out_of_range_is_rejected_not_clamped(): void
    {
        $auth = $this->registerUser();
        // رگرسیون B-05/B-06: ظرفیت خارج از بازه خطای صریح می‌گیرد، نه clamp ساکت.
        foreach ([0, 101, 500] as $capacity) {
            $this->authed($auth)->postJson('/api/rooms', [
                'name' => 'اتاق ظرفیت',
                'capacity' => $capacity,
            ])->assertStatus(400)
                ->assertJsonPath('error.code', 'VALIDATION_ERROR');
        }
    }

    public function test_shrink_requires_confirmation_and_deletes_orphan_files(): void
    {
        $auth = $this->registerUser();
        $room = $this->createRoom($auth, ['capacity' => 2]);
        $roomId = $room['id'];
        [$first, $second] = $room['speakers'];
        $this->nameSpeaker($auth, $roomId, $first['id'], 'سخنران اول');
        $this->nameSpeaker($auth, $roomId, $second['id'], 'سخنران دوم');

        // فایل اختصاصی سخنران دوم
        $upload = $this->authed($auth)->call(
            'POST',
            "/api/rooms/{$roomId}/files",
            ['upload_type' => 'speaker', 'speaker_id' => $second['id']],
            [],
            ['file' => UploadedFile::fake()->createWithContent('notes.txt', 'یادداشت سخنران دوم')],
        );
        $upload->assertOk();
        $this->assertSame(1, SpeechFile::query()->where('speaker_id', $second['id'])->count());

        $payload = [
            'name' => 'اتاق تست',
            'description' => '',
            'capacity' => 1,
            'recording_enabled' => true,
            'live_files_enabled' => true,
            'timing_mode' => 'global',
            'global_seconds' => 300,
            'order_mode' => 'manual',
            'public_enabled' => true,
            'speaker_mode_enabled' => false,
            'speaker_uploads_enabled' => false,
        ];

        // بدون تأیید صریح: ۴۰۹ با کد مشخص (محافظ C-04 نسخهٔ PHP).
        $this->authed($auth)->putJson("/api/rooms/{$roomId}", $payload)
            ->assertStatus(409)
            ->assertJsonPath('error.code', 'CONFIRM_CAPACITY_SHRINK_REQUIRED');

        // با تأیید: سخنران دوم و ردیف فایلش هر دو حذف می‌شوند (رگرسیون B-03).
        $payload['confirm_shrink'] = true;
        $this->authed($auth)->putJson("/api/rooms/{$roomId}", $payload)->assertOk();

        $detail = $this->authed($auth)->getJson("/api/rooms/{$roomId}")->json('room');
        $this->assertCount(1, $detail['speakers']);
        $this->assertSame(0, SpeechFile::query()->where('speaker_id', $second['id'])->count());
    }

    public function test_room_of_another_user_is_not_visible(): void
    {
        $owner = $this->registerUser('owner-a');
        $room = $this->createRoom($owner);

        $other = $this->registerUser('owner-b');
        $this->authed($other)->getJson("/api/rooms/{$room['id']}")
            ->assertNotFound()
            ->assertJsonPath('error.code', 'NOT_FOUND');
    }
}
