<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * دیتابیس تازهٔ نسخهٔ PHP — معادل کامل مدل‌های mas_app/db/models.py.
 * همهٔ زمان‌ها epoch میلی‌ثانیه (bigint) ذخیره می‌شوند تا قرارداد API با
 * نسخهٔ Python (فیلدهای *_ms) دقیقاً یکسان بماند و فرانت‌اند بدون تغییر کار کند.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('users', function (Blueprint $table) {
            $table->id();
            $table->string('username', 32);
            $table->string('username_key', 32)->unique();
            $table->string('password_hash', 256);
            $table->string('account_name', 120)->default('');
            $table->integer('age')->nullable();
            $table->string('job', 120)->default('');
            $table->boolean('profile_completed')->default(false);
            $table->string('role', 16)->default('user');
            $table->boolean('is_active')->default(true)->index();
            $table->string('timezone', 64)->default('Asia/Tehran');
            $table->string('calendar', 16)->default('jalali');
            $table->bigInteger('storage_used_bytes')->default(0);
            $table->integer('failed_login_count')->default(0);
            $table->bigInteger('locked_until_ms')->default(0);
            $table->string('recovery_code_hash', 64)->nullable();
            $table->bigInteger('created_at_ms');
            $table->bigInteger('updated_at_ms');
            $table->bigInteger('last_login_at_ms')->default(0);
            $table->integer('version')->default(1);
        });

        Schema::create('auth_sessions', function (Blueprint $table) {
            $table->id();
            $table->foreignId('user_id')->constrained('users')->cascadeOnDelete();
            $table->string('token_hash', 64)->unique();
            $table->string('csrf_hash', 64);
            $table->bigInteger('created_at_ms');
            $table->bigInteger('expires_at_ms')->index();
            $table->bigInteger('last_seen_at_ms');
            $table->string('ip', 64)->default('');
            $table->string('user_agent', 255)->default('');
            $table->index(['user_id', 'expires_at_ms'], 'ix_auth_sessions_user_id_expires');
        });

        Schema::create('rate_limit_buckets', function (Blueprint $table) {
            $table->id();
            $table->string('bucket_key', 160)->unique();
            $table->string('action', 32)->default('');
            $table->integer('count')->default(0);
            $table->bigInteger('window_started_at_ms');
            $table->bigInteger('blocked_until_ms')->default(0);
            $table->index('window_started_at_ms', 'ix_rate_limit_buckets_window');
        });

        Schema::create('rooms', function (Blueprint $table) {
            $table->id();
            $table->foreignId('owner_id')->constrained('users')->cascadeOnDelete();
            $table->string('name', 160);
            $table->text('description')->default('');
            $table->integer('capacity');
            $table->boolean('recording_enabled')->default(false);
            $table->boolean('live_files_enabled')->default(false);
            $table->boolean('speaker_mode_enabled')->default(false);
            $table->boolean('speaker_uploads_enabled')->default(false);
            $table->boolean('public_enabled')->default(false);
            $table->string('public_token', 43)->nullable()->unique();
            $table->bigInteger('public_token_created_at_ms')->default(0);
            $table->string('timing_mode', 16)->default('global');
            $table->integer('global_seconds')->default(300);
            $table->string('order_mode', 16)->default('manual');
            $table->bigInteger('storage_used_bytes')->default(0);
            $table->bigInteger('created_at_ms');
            $table->bigInteger('updated_at_ms');
            $table->integer('version')->default(1);
            $table->index(['owner_id', 'id'], 'ix_rooms_owner_id_id_desc');
        });

        Schema::create('speakers', function (Blueprint $table) {
            $table->id();
            $table->foreignId('room_id')->constrained('rooms')->cascadeOnDelete();
            $table->integer('order_index')->default(0);
            $table->string('name', 120)->default('');
            $table->string('gender', 16)->default('');
            $table->integer('age')->nullable();
            $table->text('description')->default('');
            $table->integer('speaking_seconds')->default(300);
            $table->boolean('is_finished')->default(false);
            $table->bigInteger('finished_at_ms')->default(0);
            $table->string('speaker_code_hash', 64)->nullable();
            $table->string('speaker_code_encrypted', 512)->nullable();
            $table->string('speaker_session_hash', 64)->nullable();
            $table->string('presence_status', 16)->default('offline');
            $table->bigInteger('presence_last_seen_at_ms')->default(0);
            $table->bigInteger('created_at_ms');
            $table->bigInteger('updated_at_ms');
            $table->unique(['room_id', 'order_index'], 'uq_speaker_room_order');
            $table->unique(['room_id', 'speaker_code_hash'], 'uq_speaker_room_code_hash');
            $table->index(['room_id', 'name'], 'ix_speakers_room_id_name');
        });

        Schema::create('speech_files', function (Blueprint $table) {
            $table->id();
            $table->foreignId('room_id')->constrained('rooms')->cascadeOnDelete();
            $table->foreignId('speaker_id')->nullable()->constrained('speakers')->nullOnDelete();
            $table->string('filename', 255);
            $table->string('storage_key', 400)->unique();
            $table->string('backend', 16)->default('local');
            $table->string('content_type', 120)->default('application/octet-stream');
            $table->bigInteger('size_bytes')->default(0);
            $table->string('upload_type', 16);
            $table->string('approval_status', 16)->default('approved');
            $table->bigInteger('duration_ms')->nullable();
            $table->string('speaker_name', 120)->default('');
            $table->string('sha256', 64)->default('');
            $table->bigInteger('created_at_ms');
            $table->bigInteger('updated_at_ms');
            $table->index(['room_id', 'upload_type', 'created_at_ms'], 'ix_speech_files_room_upload_created');
            $table->index(['upload_type', 'created_at_ms'], 'ix_speech_files_upload_type_created');
        });

        Schema::create('room_states', function (Blueprint $table) {
            $table->id();
            $table->foreignId('room_id')->unique()->constrained('rooms')->cascadeOnDelete();
            $table->foreignId('current_speaker_id')->nullable()->constrained('speakers')->nullOnDelete();
            $table->integer('current_index')->default(0);
            $table->boolean('running')->default(false);
            $table->boolean('awaiting_decision')->default(false);
            $table->bigInteger('started_at_ms')->default(0);
            $table->bigInteger('elapsed_ms')->default(0);
            $table->bigInteger('overtime_ms')->default(0);
            $table->string('stop_reason', 24)->default('');
            $table->bigInteger('updated_at_ms');
            $table->integer('version')->default(1);
        });

        Schema::create('speaker_timer_states', function (Blueprint $table) {
            $table->id();
            $table->foreignId('room_id')->constrained('rooms')->cascadeOnDelete();
            $table->foreignId('speaker_id')->constrained('speakers')->cascadeOnDelete();
            $table->bigInteger('elapsed_ms')->default(0);
            $table->bigInteger('overtime_ms')->default(0);
            $table->bigInteger('started_at_ms')->default(0);
            $table->bigInteger('updated_at_ms');
            $table->integer('version')->default(1);
            $table->unique(['room_id', 'speaker_id'], 'uq_timer_room_speaker');
        });

        Schema::create('recording_sessions', function (Blueprint $table) {
            $table->id();
            $table->foreignId('room_id')->constrained('rooms')->cascadeOnDelete();
            $table->foreignId('speaker_id')->nullable()->constrained('speakers')->nullOnDelete();
            $table->string('speaker_name', 120)->default('');
            $table->string('status', 16)->default('recording');
            $table->string('mime_type', 60)->default('audio/webm');
            $table->integer('chunk_seq')->default(0);
            $table->bigInteger('bytes_received')->default(0);
            $table->bigInteger('recorded_ms')->default(0);
            $table->bigInteger('active_since_ms')->default(0);
            $table->bigInteger('started_at_ms');
            $table->bigInteger('last_chunk_at_ms')->default(0);
            $table->bigInteger('ended_at_ms')->default(0);
            $table->foreignId('final_file_id')->nullable()->constrained('speech_files')->nullOnDelete();
            $table->string('error', 255)->default('');
            $table->integer('version')->default(1);
            $table->index(['room_id', 'status'], 'ix_recording_sessions_room_status');
            $table->index(['status', 'last_chunk_at_ms'], 'ix_recording_sessions_status_last_chunk');
        });

        Schema::create('recording_chunks', function (Blueprint $table) {
            $table->id();
            $table->foreignId('session_id')->constrained('recording_sessions')->cascadeOnDelete();
            $table->integer('seq');
            $table->string('storage_key', 400)->unique();
            $table->string('backend', 16)->default('local');
            $table->bigInteger('size_bytes')->default(0);
            $table->bigInteger('created_at_ms');
            $table->unique(['session_id', 'seq'], 'uq_chunk_session_seq');
        });

        Schema::create('cleanup_queue', function (Blueprint $table) {
            $table->id();
            $table->string('backend', 16)->default('local');
            $table->string('storage_key', 400);
            $table->string('reason', 32)->default('');
            $table->integer('attempts')->default(0);
            $table->bigInteger('next_attempt_at_ms');
            $table->string('last_error', 255)->default('');
            $table->bigInteger('created_at_ms');
            $table->unique(['backend', 'storage_key'], 'uq_cleanup_backend_key');
            $table->index('next_attempt_at_ms', 'ix_cleanup_queue_next_attempt');
        });

        Schema::create('audit_logs', function (Blueprint $table) {
            $table->id();
            $table->foreignId('actor_user_id')->nullable()->constrained('users')->nullOnDelete();
            $table->string('actor_username', 32)->default('');
            $table->string('action', 48)->index();
            $table->string('severity', 16)->default('info');
            $table->string('target_type', 32)->default('');
            $table->string('target_id', 64)->default('');
            $table->text('detail')->default('');
            $table->string('ip', 64)->default('');
            $table->string('user_agent', 255)->default('');
            $table->bigInteger('created_at_ms')->index();
            $table->index(['action', 'created_at_ms'], 'ix_audit_logs_action_created');
            $table->index(['actor_user_id', 'created_at_ms'], 'ix_audit_logs_actor_created');
        });

        $this->addCheckConstraints();
    }

    /**
     * قیود CHECK نسخهٔ Python. روی PostgreSQL با ALTER اعمال می‌شوند؛ SQLite در
     * تست‌ها از همان اعتبارسنجی‌های لایهٔ سرویس استفاده می‌کند (افزودن CHECK بعد
     * از ساخت جدول در SQLite ممکن نیست).
     */
    private function addCheckConstraints(): void
    {
        if (DB::connection()->getDriverName() !== 'pgsql') {
            return;
        }
        $checks = [
            'users' => [
                'role_valid' => "role IN ('user','admin')",
                'calendar_valid' => "calendar IN ('jalali','gregorian')",
                'age_range' => 'age IS NULL OR (age >= 1 AND age <= 120)',
                'storage_non_negative' => 'storage_used_bytes >= 0',
                'failed_login_non_negative' => 'failed_login_count >= 0',
            ],
            'rate_limit_buckets' => ['count_non_negative' => 'count >= 0'],
            'rooms' => [
                'capacity_positive' => 'capacity >= 1',
                'global_seconds_range' => 'global_seconds >= 10 AND global_seconds <= 86400',
                'storage_non_negative' => 'storage_used_bytes >= 0',
                'timing_mode_valid' => "timing_mode IN ('global','individual')",
                'order_mode_valid' => "order_mode IN ('manual','alpha','age')",
                'public_requires_token' => 'NOT public_enabled OR public_token IS NOT NULL',
            ],
            'speakers' => [
                'order_index_non_negative' => 'order_index >= 0',
                'speaking_seconds_range' => 'speaking_seconds >= 10 AND speaking_seconds <= 86400',
                'age_range' => 'age IS NULL OR (age >= 1 AND age <= 120)',
                'gender_valid' => "gender IN ('','male','female','other')",
            ],
            'speech_files' => [
                'upload_type_valid' => "upload_type IN ('common','speaker','recording')",
                'size_non_negative' => 'size_bytes >= 0',
                'duration_non_negative' => 'duration_ms IS NULL OR duration_ms >= 0',
            ],
            'room_states' => [
                'elapsed_non_negative' => 'elapsed_ms >= 0',
                'overtime_non_negative' => 'overtime_ms >= 0',
                'current_index_non_negative' => 'current_index >= 0',
                'stop_reason_valid' => "stop_reason IN ('','paused','time_up','finished','session_completed','switched')",
            ],
            'speaker_timer_states' => [
                'elapsed_non_negative' => 'elapsed_ms >= 0',
                'overtime_non_negative' => 'overtime_ms >= 0',
            ],
            'recording_sessions' => [
                'status_valid' => "status IN ('recording','paused','finalizing','saved','discarded','failed','recovered')",
                'chunk_seq_non_negative' => 'chunk_seq >= 0',
                'bytes_non_negative' => 'bytes_received >= 0',
                'recorded_ms_non_negative' => 'recorded_ms >= 0',
            ],
            'recording_chunks' => [
                'seq_non_negative' => 'seq >= 0',
                'size_positive' => 'size_bytes > 0',
            ],
            'cleanup_queue' => ['attempts_non_negative' => 'attempts >= 0'],
            'audit_logs' => ['severity_valid' => "severity IN ('info','warning','error','security')"],
        ];
        foreach ($checks as $table => $constraints) {
            foreach ($constraints as $name => $expression) {
                DB::statement("ALTER TABLE {$table} ADD CONSTRAINT {$name} CHECK ({$expression})");
            }
        }
    }

    public function down(): void
    {
        foreach ([
            'audit_logs', 'cleanup_queue', 'recording_chunks', 'recording_sessions',
            'speaker_timer_states', 'room_states', 'speech_files', 'speakers',
            'rooms', 'rate_limit_buckets', 'auth_sessions', 'users',
        ] as $table) {
            Schema::dropIfExists($table);
        }
    }
};
