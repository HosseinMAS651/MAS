<?php

/*
| معادل CORSMiddleware نسخهٔ Python: در توسعه همهٔ originها مجازند و در
| production هیچ‌کدام (فرانت‌اند و API زیر یک Nginx و هم‌origin هستند).
*/

return [
    'paths' => ['api/*', 'health', 'ready'],
    'allowed_methods' => ['*'],
    'allowed_origins' => env('APP_ENV', 'production') === 'production' ? [] : ['*'],
    'allowed_origins_patterns' => [],
    'allowed_headers' => ['*'],
    'exposed_headers' => [],
    'max_age' => 0,
    'supports_credentials' => true,
];
