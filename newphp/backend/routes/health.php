<?php

use App\Http\Controllers\Api\HealthController;
use Illuminate\Support\Facades\Route;

// در نسخهٔ FastAPI این دو مسیر در ریشه‌اند؛ اینجا هم بدون پیشوند /api ثبت می‌شوند.
Route::get('/health', [HealthController::class, 'health']);
Route::get('/ready', [HealthController::class, 'ready']);
