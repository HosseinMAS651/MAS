<?php

/*
| درایور هش رمز عبور MAS مثل نسخهٔ Python روی Argon2id است.
| پارامترها از همان متغیرهای MAS_ARGON2_* در config/mas.php خوانده می‌شوند.
| هش‌های قدیمی pbkdf2_sha256 در SecurityService به‌صورت دستی verify و بعد از
| اولین ورود موفق به Argon2id rehash می‌شوند.
*/

return [
    'driver' => 'argon2id',

    'bcrypt' => [
        'rounds' => (int) env('BCRYPT_ROUNDS', 12),
        'verify' => true,
        'limit' => null,
    ],

    'argon' => [
        'memory' => (int) env('MAS_ARGON2_MEMORY_COST_KIB', 19456),
        'threads' => (int) env('MAS_ARGON2_PARALLELISM', 1),
        'time' => (int) env('MAS_ARGON2_TIME_COST', 2),
        'verify' => true,
    ],

    'rehash_on_login' => true,
];
