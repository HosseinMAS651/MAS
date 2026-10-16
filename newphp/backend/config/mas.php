<?php

/*
|--------------------------------------------------------------------------
| تنظیمات اختصاصی MAS
|--------------------------------------------------------------------------
| معادل mas_app/config.py در نسخهٔ Python. همهٔ متغیرها با پیشوند MAS_
| خوانده می‌شوند تا نام‌ها و مقادیر پیش‌فرض بین دو نسخه یکسان بمانند.
| مقادیر مشتق‌شده (بایت/ثانیه) در App\Support\Settings محاسبه می‌شوند.
*/

return [
    // عمومی
    'env' => env('MAS_ENV', 'development'), // development | test | production
    'log_level' => env('MAS_LOG_LEVEL', 'INFO'),
    'public_base_url' => env('MAS_PUBLIC_BASE_URL', ''),
    'enable_docs' => env('MAS_ENABLE_DOCS'),

    // امنیت — MAS_SECRET_KEY برای HMAC توکن‌ها استفاده می‌شود (مستقل از APP_KEY).
    'secret_key' => env('MAS_SECRET_KEY', ''),
    'argon2_time_cost' => (int) env('MAS_ARGON2_TIME_COST', 2),
    'argon2_memory_cost_kib' => (int) env('MAS_ARGON2_MEMORY_COST_KIB', 19456),
    'argon2_parallelism' => (int) env('MAS_ARGON2_PARALLELISM', 1),

    // دیتابیس (اتصال خود Laravel از DB_* خوانده می‌شود؛ این‌ها فقط محدودیت‌ها هستند)
    'allow_sqlite_in_production' => (bool) env('MAS_ALLOW_SQLITE_IN_PRODUCTION', false),
    'db_pool_size' => (int) env('MAS_DB_POOL_SIZE', 5),

    // ذخیره‌سازی
    'storage_backend' => env('MAS_STORAGE_BACKEND', 'local'), // local | s3
    'storage_dir' => env('MAS_STORAGE_DIR', './uploads'),
    's3_endpoint_url' => env('MAS_S3_ENDPOINT_URL', ''),
    's3_region' => env('MAS_S3_REGION', 'us-east-1'),
    's3_bucket' => env('MAS_S3_BUCKET', ''),
    's3_access_key_id' => env('MAS_S3_ACCESS_KEY_ID', ''),
    's3_secret_access_key' => env('MAS_S3_SECRET_ACCESS_KEY', ''),
    's3_prefix' => env('MAS_S3_PREFIX', 'mas/'),
    's3_addressing_style' => env('MAS_S3_ADDRESSING_STYLE', 'virtual'), // virtual | path
    's3_use_presigned_download' => (bool) env('MAS_S3_USE_PRESIGNED_DOWNLOAD', false),
    's3_presigned_ttl_seconds' => (int) env('MAS_S3_PRESIGNED_TTL_SECONDS', 900),

    // سهمیه‌ها و محدودیت‌ها
    'max_upload_mb' => (int) env('MAS_MAX_UPLOAD_MB', 50),
    'max_room_storage_mb' => (int) env('MAS_MAX_ROOM_STORAGE_MB', 2048),
    'max_user_storage_mb' => (int) env('MAS_MAX_USER_STORAGE_MB', 10240),
    'max_rooms_per_user' => (int) env('MAS_MAX_ROOMS_PER_USER', 50),
    'min_room_capacity' => (int) env('MAS_MIN_ROOM_CAPACITY', 1),
    'max_room_capacity' => (int) env('MAS_MAX_ROOM_CAPACITY', 100),
    'max_speaker_name_length' => (int) env('MAS_MAX_SPEAKER_NAME_LENGTH', 120),
    'max_room_name_length' => (int) env('MAS_MAX_ROOM_NAME_LENGTH', 160),
    'max_description_length' => (int) env('MAS_MAX_DESCRIPTION_LENGTH', 4000),
    'allowed_upload_extensions' => env(
        'MAS_ALLOWED_UPLOAD_EXTENSIONS',
        '.pdf,.doc,.docx,.odt,.txt,.md,.rtf,.ppt,.pptx,.odp,.xls,.xlsx,.ods,.csv,'
        .'.png,.jpg,.jpeg,.gif,.webp,.svgz,.bmp,.tiff,'
        .'.mp3,.m4a,.aac,.ogg,.oga,.opus,.wav,.flac,.weba,'
        .'.mp4,.m4v,.webm,.ogv,.mov,.avi,.mkv'
    ),

    // ضبط صوت
    'max_recording_minutes' => (int) env('MAS_MAX_RECORDING_MINUTES', 180),
    'recording_bitrate_kbps' => (int) env('MAS_RECORDING_BITRATE_KBPS', 32),
    'recording_chunk_seconds' => (int) env('MAS_RECORDING_CHUNK_SECONDS', 5),
    'max_recording_chunk_mb' => (int) env('MAS_MAX_RECORDING_CHUNK_MB', 1),
    'recording_abandon_minutes' => (int) env('MAS_RECORDING_ABANDON_MINUTES', 30),
    'recording_max_chunks' => (int) env('MAS_RECORDING_MAX_CHUNKS', 40000),

    // نشست و کوکی
    'session_idle_minutes' => (int) env('MAS_SESSION_IDLE_MINUTES', 720),
    'session_absolute_days' => (int) env('MAS_SESSION_ABSOLUTE_DAYS', 30),
    'cookie_name' => env('MAS_COOKIE_NAME', 'mas_session'),
    'cookie_secure' => (bool) env('MAS_COOKIE_SECURE', false),
    'cookie_samesite' => env('MAS_COOKIE_SAMESITE', 'lax'), // lax | strict | none
    'cookie_domain' => env('MAS_COOKIE_DOMAIN', ''),
    'csrf_cookie_name' => env('MAS_CSRF_COOKIE_NAME', 'mas_csrf'),
    'csrf_header_name' => env('MAS_CSRF_HEADER_NAME', 'X-CSRF-Token'),
    'csrf_protection_enabled' => (bool) env('MAS_CSRF_PROTECTION_ENABLED', true),

    // پروکسی و محدودسازی نرخ
    'trusted_proxy_hops' => (int) env('MAS_TRUSTED_PROXY_HOPS', 1),
    'login_max_attempts' => (int) env('MAS_LOGIN_MAX_ATTEMPTS', 10),
    'login_window_seconds' => (int) env('MAS_LOGIN_WINDOW_SECONDS', 600),
    'register_max_per_ip' => (int) env('MAS_REGISTER_MAX_PER_IP', 20),
    'register_window_seconds' => (int) env('MAS_REGISTER_WINDOW_SECONDS', 3600),
    'public_max_per_ip' => (int) env('MAS_PUBLIC_MAX_PER_IP', 3000),
    'public_window_seconds' => (int) env('MAS_PUBLIC_WINDOW_SECONDS', 60),
    'api_max_per_minute' => (int) env('MAS_API_MAX_PER_MINUTE', 600),
    'reaction_max_per_minute' => (int) env('MAS_REACTION_MAX_PER_MINUTE', 10),
    'reaction_poll_max_per_minute' => (int) env('MAS_REACTION_POLL_MAX_PER_MINUTE', 120),
    'recovery_max_attempts' => (int) env('MAS_RECOVERY_MAX_ATTEMPTS', 10),
    'recovery_window_seconds' => (int) env('MAS_RECOVERY_WINDOW_SECONDS', 600),
    'speaker_code_max_attempts' => (int) env('MAS_SPEAKER_CODE_MAX_ATTEMPTS', 10),
    'speaker_code_window_seconds' => (int) env('MAS_SPEAKER_CODE_WINDOW_SECONDS', 600),

    // اتاق عمومی
    'public_state_max_age_seconds' => (int) env('MAS_PUBLIC_STATE_MAX_AGE_SECONDS', 2),

    // نگهداری پس‌زمینه
    'maintenance_enabled' => (bool) env('MAS_MAINTENANCE_ENABLED', true),
    'maintenance_interval_seconds' => (int) env('MAS_MAINTENANCE_INTERVAL_SECONDS', 300),
    'cleanup_queue_batch' => (int) env('MAS_CLEANUP_QUEUE_BATCH', 25),
];
