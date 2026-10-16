<?php

namespace App\Services;

use App\Exceptions\ConflictError;
use App\Exceptions\NotFoundError;
use App\Exceptions\ValidationAppError;
use App\Models\Room;
use App\Models\RoomState;
use App\Models\Speaker;
use App\Models\SpeakerTimerState;
use App\Support\Mas;
use Illuminate\Support\Facades\DB;

/**
 * معادل mas_app/services/timer_service.py — ماشین وضعیت تایمر اتاق با
 * قفل ردیفی روی RoomState. snapshot آرایه‌ای با همان کلیدهای نسخهٔ Python
 * برمی‌گرداند تا Presenterها دقیقاً همان JSON قبلی را بسازند.
 */
class TimerService
{
    public function __construct(private readonly RecordingService $recordingService)
    {
    }

    public function ensureRoomState(Room $room): RoomState
    {
        $state = $room->state()->first();
        if ($state === null) {
            $first = $room->speakers()->first();
            $state = RoomState::create([
                'room_id' => $room->id,
                'current_speaker_id' => $first?->id,
                'current_index' => 0,
                'running' => false,
                'awaiting_decision' => false,
                'started_at_ms' => 0,
                'elapsed_ms' => 0,
                'overtime_ms' => 0,
                'stop_reason' => '',
                'updated_at_ms' => Mas::nowMs(),
                'version' => 1,
            ]);
        }

        return $state;
    }

    private function lockState(Room $room): RoomState
    {
        $state = RoomState::query()->where('room_id', $room->id)->lockForUpdate()->first();
        if ($state === null) {
            $state = $this->ensureRoomState($room);
        }

        return $state;
    }

    public function ensureSpeakerTimer(int $roomId, int $speakerId): SpeakerTimerState
    {
        $timer = SpeakerTimerState::query()
            ->where('room_id', $roomId)->where('speaker_id', $speakerId)
            ->first();
        if ($timer === null) {
            $timer = SpeakerTimerState::create([
                'room_id' => $roomId,
                'speaker_id' => $speakerId,
                'elapsed_ms' => 0,
                'overtime_ms' => 0,
                'started_at_ms' => 0,
                'updated_at_ms' => Mas::nowMs(),
                'version' => 1,
            ]);
        }

        return $timer;
    }

    private function speakerLimitMs(Room $room, Speaker $speaker): int
    {
        return ($room->timing_mode === 'individual' ? $speaker->speaking_seconds : $room->global_seconds) * 1000;
    }

    private function syncCurrentTimer(RoomState $state, Room $room, Speaker $speaker, int $nowMs): void
    {
        if ($state->running && $state->started_at_ms > 0) {
            $delta = Mas::nonNegativeDelta($state->started_at_ms, $nowMs);
            if ($state->awaiting_decision) {
                $state->overtime_ms += $delta;
            } else {
                $state->elapsed_ms += $delta;
            }
        }
        $timer = $this->ensureSpeakerTimer($room->id, $speaker->id);
        $timer->elapsed_ms = $state->elapsed_ms;
        $timer->overtime_ms = $state->overtime_ms;
        $timer->started_at_ms = 0;
        $timer->updated_at_ms = $nowMs;
        $timer->version += 1;
        $timer->save();
    }

    /** @param list<Speaker> $speakers */
    private function currentSpeaker(array $speakers, RoomState $state): ?Speaker
    {
        if ($state->current_speaker_id !== null) {
            foreach ($speakers as $sp) {
                if ($sp->id === $state->current_speaker_id) {
                    return $sp;
                }
            }
        }
        foreach ($speakers as $sp) {
            if (! $sp->is_finished) {
                return $sp;
            }
        }

        return $speakers[0] ?? null;
    }

    private function deferSpeakerRecordingFinish(Room $room, Speaker $speaker): void
    {
        // ضبط دستگاه سخنران فقط pause می‌شود؛ خود دستگاه بعد از تحویل نوبت flush و finalize می‌کند.
        $rec = $this->recordingService->getActiveSession($room->id, $speaker->id, lock: true);
        if (! $rec) {
            return;
        }
        if ($rec->bytes_received > 0 || $rec->recorded_ms > 0) {
            $this->recordingService->pause($room->id, $speaker->id);
        } else {
            $this->recordingService->discardRecording($rec);
        }
    }

    /**
     * @return array<string, mixed> snapshot با کلیدهای نسخهٔ Python
     */
    public function getSnapshot(Room $room, ?int $nowMs = null): array
    {
        return DB::transaction(function () use ($room, $nowMs) {
            $state = $this->ensureRoomState($room);
            $now = $nowMs ?? Mas::nowMs();
            $speakers = $room->speakers()->get()->all();
            $current = $this->currentSpeaker($speakers, $state);

            if ($current && $state->current_speaker_id !== $current->id) {
                $state->current_speaker_id = $current->id;
                $state->current_index = array_search($current, $speakers, true);
                $timer = $this->ensureSpeakerTimer($room->id, $current->id);
                $state->elapsed_ms = $timer->elapsed_ms;
                $state->overtime_ms = $timer->overtime_ms;
                $state->version += 1;
                $state->save();
            }

            $limitMs = $current ? $this->speakerLimitMs($room, $current) : 300000;
            $elapsed = $state->elapsed_ms;
            $overtime = $state->overtime_ms;

            if ($state->running && $state->started_at_ms > 0) {
                $delta = Mas::nonNegativeDelta($state->started_at_ms, $now);
                if ($state->awaiting_decision) {
                    $overtime = $state->overtime_ms + $delta;
                } else {
                    $potential = $state->elapsed_ms + $delta;
                    if ($potential >= $limitMs) {
                        // رسیدن به سقف: تایمر متوقف و منتظر تصمیم (ادامهٔ اضافه‌وقت یا پایان) می‌شود.
                        $state->running = false;
                        $state->awaiting_decision = true;
                        $state->elapsed_ms = $limitMs;
                        $state->started_at_ms = 0;
                        $state->stop_reason = 'time_up';
                        $state->version += 1;
                        $state->save();
                        $elapsed = $limitMs;
                        $overtime = 0;
                        if ($current) {
                            $timer = $this->ensureSpeakerTimer($room->id, $current->id);
                            $timer->elapsed_ms = $limitMs;
                            $timer->overtime_ms = $state->overtime_ms;
                            $timer->started_at_ms = 0;
                            $timer->updated_at_ms = $now;
                            $timer->version += 1;
                            $timer->save();
                            if ($room->recording_enabled || $room->speaker_mode_enabled) {
                                $this->recordingService->pause($room->id, $current->id);
                            }
                        }
                    } else {
                        $elapsed = $potential;
                    }
                }
            }

            $recStatus = 'inactive';
            if (($room->recording_enabled || $room->speaker_mode_enabled) && $current) {
                $rec = $this->recordingService->getActiveSession($room->id, $current->id);
                if ($rec) {
                    $recStatus = $rec->status;
                }
            }

            $finished = 0;
            foreach ($speakers as $s) {
                if ($s->is_finished) {
                    $finished++;
                }
            }

            return [
                'room_id' => $room->id,
                'version' => $state->version,
                'running' => $state->running,
                'awaiting_decision' => $state->awaiting_decision,
                'stop_reason' => $state->stop_reason,
                'current_index' => $state->current_index,
                'current_speaker_id' => $current?->id,
                'current_speaker' => $current,
                'elapsed_ms' => $elapsed,
                'remaining_ms' => max(0, $limitMs - $elapsed),
                'overtime_ms' => $overtime,
                'limit_ms' => $limitMs,
                'total_speakers' => count($speakers),
                'finished_speakers' => $finished,
                'speakers' => $speakers,
                'recording_status' => $recStatus,
            ];
        });
    }

    /** @return array<string, mixed> */
    public function handleAction(
        Room $room,
        string $action,
        ?int $speakerId = null,
        ?int $expectedVersion = null,
    ): array {
        return DB::transaction(function () use ($room, $action, $speakerId, $expectedVersion) {
            $state = $this->lockState($room);
            $now = Mas::nowMs();
            $this->getSnapshot($room, $now);
            // getSnapshot روی نمونهٔ دیگری از همین ردیف کار می‌کند (در Python
            // identity map همین شیء بود)؛ پس state را تازه می‌خوانیم تا گذارهای
            // خودکار مثل time_up روی تصمیم اکشن اثر درست بگذارند.
            $state->refresh();

            if ($expectedVersion !== null && $state->version !== $expectedVersion) {
                throw new ConflictError(
                    'وضعیت اتاق تغییر کرده است؛ لطفاً اطلاعات اتاق را تازه‌سازی کنید.',
                    code: 'STATE_VERSION_CONFLICT',
                    details: ['current_version' => $state->version],
                );
            }

            $speakers = $room->speakers()->get()->all();
            $current = $this->currentSpeaker($speakers, $state);
            if ($current && $state->current_speaker_id !== $current->id) {
                $state->current_speaker_id = $current->id;
                $state->current_index = array_search($current, $speakers, true);
            }
            $recordingOn = $room->recording_enabled || $room->speaker_mode_enabled;

            switch ($action) {
                case 'start':
                    if (! $current) {
                        throw new ValidationAppError('هیچ سخنرانی برای شروع در این اتاق وجود ندارد.');
                    }
                    if ($current->is_finished) {
                        throw new ValidationAppError('این سخنران پایان یافته است. ابتدا او را از فریز خارج کنید.');
                    }
                    if ($state->running) {
                        throw new ConflictError('تایمر در حال اجراست.', code: 'TIMER_ALREADY_RUNNING');
                    }
                    if ($state->awaiting_decision) {
                        throw new ValidationAppError('ابتدا دربارهٔ ادامهٔ زمان اضافه تصمیم بگیرید.');
                    }
                    $state->running = true;
                    $state->started_at_ms = $now;
                    $state->stop_reason = '';
                    $state->version += 1;
                    if ($recordingOn) {
                        $this->recordingService->startOrResume($room, $current);
                    }
                    break;

                case 'pause':
                    if ($state->running && $current) {
                        $this->syncCurrentTimer($state, $room, $current, $now);
                        $state->running = false;
                        $state->started_at_ms = 0;
                        $state->stop_reason = 'paused';
                        $state->version += 1;
                        if ($recordingOn) {
                            $this->recordingService->pause($room->id, $current->id);
                        }
                    }
                    break;

                case 'resume':
                    if (! $current || $current->is_finished) {
                        throw new ValidationAppError('امکان از سرگیری وجود ندارد.');
                    }
                    if ($state->running) {
                        throw new ConflictError('تایمر در حال اجراست.', code: 'TIMER_ALREADY_RUNNING');
                    }
                    if ($state->awaiting_decision) {
                        throw new ValidationAppError('برای ادامهٔ زمان اضافه از گزینهٔ «ادامه» استفاده کنید.');
                    }
                    $state->running = true;
                    $state->started_at_ms = $now;
                    $state->stop_reason = '';
                    $state->version += 1;
                    if ($recordingOn) {
                        $this->recordingService->startOrResume($room, $current);
                    }
                    break;

                case 'continue_overtime':
                    if (! $current) {
                        throw new ValidationAppError('سخنرانی یافت نشد.');
                    }
                    if (! $state->awaiting_decision) {
                        throw new ValidationAppError('در حال حاضر تصمیمی برای زمان اضافه مورد نیاز نیست.');
                    }
                    if ($current->is_finished) {
                        throw new ValidationAppError('این سخنران پایان یافته است.');
                    }
                    $state->running = true;
                    $state->awaiting_decision = true;
                    $state->started_at_ms = $now;
                    $state->stop_reason = '';
                    $state->version += 1;
                    if ($recordingOn) {
                        $this->recordingService->startOrResume($room, $current);
                    }
                    break;

                case 'finish':
                case 'finish_overtime':
                    if (! $current) {
                        throw new ValidationAppError('سخنرانی فعلی یافت نشد.');
                    }
                    $this->syncCurrentTimer($state, $room, $current, $now);
                    $current->is_finished = true;
                    $current->finished_at_ms = $now;
                    $current->updated_at_ms = $now;
                    $current->save();

                    if ($room->speaker_mode_enabled) {
                        $this->deferSpeakerRecordingFinish($room, $current);
                    } elseif ($room->recording_enabled) {
                        $rec = $this->recordingService->getActiveSession($room->id, $current->id, lock: true);
                        if ($rec) {
                            $this->recordingService->finishAndSave($rec);
                        }
                    }

                    $remaining = array_values(array_filter(
                        $speakers,
                        fn (Speaker $s) => ! $s->is_finished && $s->id !== $current->id,
                    ));
                    $next = null;
                    foreach ($remaining as $candidate) {
                        if ($candidate->order_index > $current->order_index) {
                            $next = $candidate;
                            break;
                        }
                    }
                    $next ??= ($remaining[0] ?? null);

                    if ($next) {
                        $nextTimer = $this->ensureSpeakerTimer($room->id, $next->id);
                        $state->current_speaker_id = $next->id;
                        $state->current_index = array_search($next, $speakers, true);
                        $state->elapsed_ms = $nextTimer->elapsed_ms;
                        $state->overtime_ms = $nextTimer->overtime_ms;
                    } else {
                        $state->current_speaker_id = null;
                        $state->current_index = 0;
                        $state->elapsed_ms = 0;
                        $state->overtime_ms = 0;
                    }
                    $state->running = false;
                    $state->awaiting_decision = false;
                    $state->started_at_ms = 0;
                    $state->stop_reason = 'finished';
                    $state->version += 1;
                    break;

                case 'reset':
                    if ($current) {
                        if ($recordingOn) {
                            $rec = $this->recordingService->getActiveSession($room->id, $current->id, lock: true);
                            if ($rec) {
                                $this->recordingService->discardRecording($rec);
                            }
                        }
                        $state->running = false;
                        $state->awaiting_decision = false;
                        $state->started_at_ms = 0;
                        $state->elapsed_ms = 0;
                        $state->overtime_ms = 0;
                        $state->stop_reason = '';
                        $timer = $this->ensureSpeakerTimer($room->id, $current->id);
                        $timer->elapsed_ms = 0;
                        $timer->overtime_ms = 0;
                        $timer->started_at_ms = 0;
                        $timer->updated_at_ms = $now;
                        $timer->version += 1;
                        $timer->save();
                        $state->version += 1;
                    }
                    break;

                case 'goto':
                    if ($speakerId === null) {
                        throw new ValidationAppError('شناسهٔ سخنران الزامی است.');
                    }
                    $target = null;
                    foreach ($speakers as $s) {
                        if ($s->id === $speakerId) {
                            $target = $s;
                            break;
                        }
                    }
                    if (! $target) {
                        throw new NotFoundError('سخنران مورد نظر یافت نشد.');
                    }
                    if ($current && $current->id === $target->id) {
                        // کلیک روی سخنران فعلی عمداً بی‌اثر است: زمان ریست نمی‌شود.
                        return $this->getSnapshot($room, $now);
                    }
                    if ($current) {
                        $this->syncCurrentTimer($state, $room, $current, $now);
                        if ($room->speaker_mode_enabled) {
                            $this->deferSpeakerRecordingFinish($room, $current);
                        } elseif ($room->recording_enabled) {
                            $rec = $this->recordingService->getActiveSession($room->id, $current->id, lock: true);
                            if ($rec) {
                                $this->recordingService->finishAndSave($rec);
                            }
                        }
                    }
                    $targetTimer = $this->ensureSpeakerTimer($room->id, $target->id);
                    $state->current_speaker_id = $target->id;
                    $state->current_index = array_search($target, $speakers, true);
                    $state->elapsed_ms = $targetTimer->elapsed_ms;
                    $state->overtime_ms = $targetTimer->overtime_ms;
                    $state->running = false;
                    $state->awaiting_decision = false;
                    $state->started_at_ms = 0;
                    $state->stop_reason = 'switched';
                    $state->version += 1;
                    break;

                default:
                    throw new ValidationAppError('دستور تایمر نامعتبر است.');
            }

            $state->updated_at_ms = $now;
            $state->save();

            return $this->getSnapshot($room, $now);
        });
    }
}
