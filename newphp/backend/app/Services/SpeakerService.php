<?php

namespace App\Services;

use App\Exceptions\AppError;
use App\Exceptions\NotFoundError;
use App\Exceptions\ValidationAppError;
use App\Models\CleanupQueue;
use App\Models\RecordingSession;
use App\Models\Room;
use App\Models\Speaker;
use App\Models\SpeakerTimerState;
use App\Models\SpeechFile;
use App\Models\User;
use App\Support\Mas;
use Illuminate\Support\Facades\DB;

/** معادل mas_app/services/speaker_service.py (افزودن/ویرایش/حذف/ترتیب/فریز). */
class SpeakerService
{
    public function addSpeaker(
        Room $roomParam,
        string $name = '',
        string $gender = '',
        ?int $age = null,
        string $description = '',
        ?int $speakingSeconds = null,
    ): Speaker {
        return DB::transaction(function () use ($roomParam, $name, $gender, $age, $description, $speakingSeconds) {
            $room = Room::query()->where('id', $roomParam->id)->lockForUpdate()->firstOrFail();
            $count = Speaker::query()->where('room_id', $room->id)->count();
            if ($count >= $room->capacity) {
                throw new ValidationAppError(
                    "ظرفیت اتاق ({$room->capacity} نفر) پر است. برای افزودن سخنران، ابتدا ظرفیت اتاق را افزایش دهید."
                );
            }
            $secs = ($room->timing_mode === 'individual' && $speakingSeconds)
                ? $speakingSeconds
                : $room->global_seconds;
            $now = Mas::nowMs();

            $speaker = Speaker::create([
                'room_id' => $room->id,
                'order_index' => $count,
                'name' => Mas::normalizePersianText($name),
                'gender' => $gender,
                'age' => $age,
                'description' => Mas::normalizePersianText($description),
                'speaking_seconds' => $secs,
                'is_finished' => false,
                'finished_at_ms' => 0,
                'created_at_ms' => $now,
                'updated_at_ms' => $now,
            ]);
            SpeakerTimerState::create([
                'room_id' => $room->id,
                'speaker_id' => $speaker->id,
                'elapsed_ms' => 0,
                'overtime_ms' => 0,
                'started_at_ms' => 0,
                'updated_at_ms' => $now,
                'version' => 1,
            ]);

            return $speaker;
        });
    }

    public function updateSpeaker(
        Speaker $speakerParam,
        string $name,
        string $gender = '',
        ?int $age = null,
        string $description = '',
        ?int $speakingSeconds = null,
    ): Speaker {
        return DB::transaction(function () use ($speakerParam, $name, $gender, $age, $description, $speakingSeconds) {
            $room = Room::query()->where('id', $speakerParam->room_id)->lockForUpdate()->firstOrFail();
            $speaker = Speaker::query()
                ->where('id', $speakerParam->id)->where('room_id', $room->id)
                ->firstOrFail();

            $speaker->name = Mas::normalizePersianText($name);
            $speaker->gender = $gender;
            $speaker->age = $age;
            $speaker->description = Mas::normalizePersianText($description);
            if ($room->timing_mode === 'individual' && $speakingSeconds) {
                $speaker->speaking_seconds = $speakingSeconds;
            }
            // ویرایش نام به‌معنای جایگزینی سخنران نیست: وضعیت پایان و زمان انباشته حفظ می‌شود.
            $speaker->updated_at_ms = Mas::nowMs();
            $speaker->save();

            if (in_array($room->order_mode, ['alpha', 'age'], true)) {
                RoomService::applyRoomSpeakerOrder($room);
            }

            $state = $room->state()->first();
            if ($state) {
                $ordered = $room->speakers()->get()->all();
                $current = null;
                foreach ($ordered as $item) {
                    if ($item->id === $state->current_speaker_id) {
                        $current = $item;
                        break;
                    }
                }
                $state->current_index = $current ? array_search($current, $ordered, true) : 0;
                $state->version += 1;
                $state->updated_at_ms = Mas::nowMs();
                $state->save();
            }

            return $speaker;
        });
    }

    public function deleteSpeaker(
        Room $roomParam,
        int $speakerId,
        ?bool $saveRecording = null,
        ?RecordingService $recordingService = null,
    ): void {
        DB::transaction(function () use ($roomParam, $speakerId, $saveRecording, $recordingService) {
            $room = Room::query()->where('id', $roomParam->id)->lockForUpdate()->firstOrFail();
            $speaker = Speaker::query()
                ->where('id', $speakerId)->where('room_id', $room->id)
                ->first();
            if (! $speaker) {
                throw new NotFoundError('سخنران مورد نظر یافت نشد.');
            }

            $activeRec = RecordingSession::query()
                ->where('room_id', $room->id)
                ->where('speaker_id', $speaker->id)
                ->whereIn('status', ['recording', 'paused', 'finalizing'])
                ->first();

            if ($activeRec && $activeRec->status === 'finalizing') {
                throw new AppError(
                    'ضبط این سخنران در حال ذخیره‌سازی است؛ پس از پایان ذخیره دوباره تلاش کنید.',
                    code: 'RECORDING_FINALIZING',
                    details: ['session_id' => $activeRec->id],
                    statusCode: 409,
                );
            }

            if ($activeRec && ($activeRec->bytes_received > 0 || $activeRec->recorded_ms > 0)) {
                if ($saveRecording === null) {
                    throw new AppError(
                        'برای این سخنران یک ضبط فعال وجود دارد. لطفاً مشخص کنید فایل ذخیره شود یا دور ریخته شود.',
                        code: 'RECORDING_ACTIVE_PROMPT_REQUIRED',
                        details: [
                            'session_id' => $activeRec->id,
                            'speaker_name' => $speaker->name !== '' ? $speaker->name : 'سخنران',
                            'recorded_ms' => $activeRec->recorded_ms,
                        ],
                        statusCode: 409,
                    );
                }
                if ($recordingService !== null) {
                    if ($saveRecording) {
                        $recordingService->finishAndSave($activeRec);
                    } else {
                        $recordingService->discardRecording($activeRec);
                    }
                }
            } elseif ($activeRec && $recordingService !== null) {
                // نشست خالی هم اسلات ضبط فعال را نگه می‌دارد؛ پیش از حذف دور ریخته می‌شود.
                $recordingService->discardRecording($activeRec);
            }

            $owner = User::query()->where('id', $room->owner_id)->lockForUpdate()->first();
            foreach (SpeechFile::query()->where('speaker_id', $speaker->id)->where('upload_type', 'speaker')->get() as $f) {
                $room->storage_used_bytes = max(0, $room->storage_used_bytes - $f->size_bytes);
                if ($owner) {
                    $owner->storage_used_bytes = max(0, $owner->storage_used_bytes - $f->size_bytes);
                }
                CleanupQueue::enqueue($f->backend, $f->storage_key, 'speaker_deleted');
                $f->delete();
            }
            $room->save();
            $owner?->save();

            $state = $room->state()->first();
            if ($state && $state->current_speaker_id === $speaker->id) {
                $state->current_speaker_id = null;
                $state->running = false;
                $state->awaiting_decision = false;
                $state->save();
            }

            $speaker->delete();

            // بازشماری دو مرحله‌ای بدون نقض یکتایی (room_id, order_index) — رفع C-01
            $remaining = Speaker::query()
                ->where('room_id', $room->id)->orderBy('order_index')->get()->all();
            foreach ($remaining as $idx => $sp) {
                $sp->order_index = 100000 + $idx;
                $sp->save();
            }
            foreach ($remaining as $idx => $sp) {
                $sp->order_index = $idx;
                $sp->save();
            }

            if ($state) {
                $current = null;
                foreach ($remaining as $sp) {
                    if ($sp->id === $state->current_speaker_id) {
                        $current = $sp;
                        break;
                    }
                }
                if ($current === null) {
                    foreach ($remaining as $sp) {
                        if (! $sp->is_finished) {
                            $current = $sp;
                            break;
                        }
                    }
                    $current ??= ($remaining[0] ?? null);
                    $state->running = false;
                    $state->awaiting_decision = false;
                    $state->started_at_ms = 0;
                    $timer = $current?->timer()->first();
                    $state->elapsed_ms = $timer?->elapsed_ms ?? 0;
                    $state->overtime_ms = $timer?->overtime_ms ?? 0;
                    $state->stop_reason = 'switched';
                }
                $state->current_speaker_id = $current?->id;
                $state->current_index = $current ? array_search($current, $remaining, true) : 0;
                $state->version += 1;
                $state->updated_at_ms = Mas::nowMs();
                $state->save();
            }
        });
    }

    /** @param list<int> $speakerIds */
    public function reorderSpeakers(Room $roomParam, array $speakerIds): void
    {
        DB::transaction(function () use ($roomParam, $speakerIds) {
            $room = Room::query()->where('id', $roomParam->id)->lockForUpdate()->firstOrFail();
            $speakers = Speaker::query()->where('room_id', $room->id)->get();
            $map = [];
            foreach ($speakers as $sp) {
                $map[$sp->id] = $sp;
            }
            $ids = array_map('intval', $speakerIds);
            if (count($ids) !== count(array_unique($ids))
                || array_diff(array_keys($map), $ids) !== []
                || array_diff($ids, array_keys($map)) !== []) {
                throw new ValidationAppError('لیست شناسه‌های سخنران‌ها نامعتبر یا ناقص است.');
            }
            foreach ($ids as $idx => $id) {
                $map[$id]->order_index = 100000 + $idx;
                $map[$id]->save();
            }
            foreach ($ids as $idx => $id) {
                $map[$id]->order_index = $idx;
                $map[$id]->save();
            }
            $state = $room->state()->first();
            if ($state) {
                $pos = array_search($state->current_speaker_id, $ids, true);
                $state->current_index = $pos === false ? 0 : $pos;
                $state->version += 1;
                $state->updated_at_ms = Mas::nowMs();
                $state->save();
            }
        });
    }

    public function unfreezeSpeaker(Room $roomParam, int $speakerId): Speaker
    {
        return DB::transaction(function () use ($roomParam, $speakerId) {
            $room = Room::query()->where('id', $roomParam->id)->lockForUpdate()->firstOrFail();
            $speaker = Speaker::query()
                ->where('id', $speakerId)->where('room_id', $room->id)
                ->first();
            if (! $speaker) {
                throw new NotFoundError('سخنران مورد نظر یافت نشد.');
            }
            $speaker->is_finished = false;
            $speaker->finished_at_ms = 0;
            $speaker->updated_at_ms = Mas::nowMs();
            $speaker->save();

            return $speaker;
        });
    }

    public function resetAllSpeakers(Room $roomParam, ?RecordingService $recordingService = null): void
    {
        DB::transaction(function () use ($roomParam, $recordingService) {
            $room = Room::query()->where('id', $roomParam->id)->lockForUpdate()->firstOrFail();
            $active = RecordingSession::query()
                ->where('room_id', $room->id)
                ->whereIn('status', ['recording', 'paused', 'finalizing'])
                ->lockForUpdate()->get();
            if ($recordingService !== null) {
                foreach ($active as $rec) {
                    $recordingService->discardRecording($rec);
                }
            }
            $speakers = Speaker::query()->where('room_id', $room->id)->orderBy('order_index')->get();
            $now = Mas::nowMs();
            foreach ($speakers as $sp) {
                $sp->is_finished = false;
                $sp->finished_at_ms = 0;
                $sp->updated_at_ms = $now;
                $sp->save();
                $timer = $sp->timer()->first();
                if ($timer) {
                    $timer->elapsed_ms = 0;
                    $timer->overtime_ms = 0;
                    $timer->started_at_ms = 0;
                    $timer->updated_at_ms = $now;
                    $timer->save();
                }
            }
            $state = $room->state()->first();
            if ($state) {
                $state->running = false;
                $state->awaiting_decision = false;
                $state->elapsed_ms = 0;
                $state->overtime_ms = 0;
                $state->started_at_ms = 0;
                $state->current_index = 0;
                $state->current_speaker_id = $speakers->first()?->id;
                $state->updated_at_ms = $now;
                $state->version += 1;
                $state->save();
            }
        });
    }
}
