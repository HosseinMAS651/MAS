<?php

use App\Http\Controllers\Api\AdminController;
use App\Http\Controllers\Api\AuthController;
use App\Http\Controllers\Api\PublicController;
use App\Http\Controllers\Api\RecordingController;
use App\Http\Controllers\Api\RoomController;
use App\Http\Controllers\Api\SpeakerAccessController;
use App\Http\Controllers\Api\SpeakerController;
use App\Http\Controllers\Api\TimerController;
use Illuminate\Support\Facades\Route;

/*
|--------------------------------------------------------------------------
| MAS API Routes — دقیقاً همان ۵۵ endpoint نسخهٔ FastAPI
|--------------------------------------------------------------------------
*/

// ── احراز هویت ────────────────────────────────────────────────────────────
Route::prefix('auth')->group(function (): void {
    Route::post('/register', [AuthController::class, 'register']);
    Route::post('/login', [AuthController::class, 'login']);
    Route::post('/recover-password', [AuthController::class, 'recoverPassword']);

    Route::middleware('mas.auth')->group(function (): void {
        Route::post('/logout', [AuthController::class, 'logout']);
        Route::get('/me', [AuthController::class, 'me']);
        Route::post('/profile', [AuthController::class, 'profile']);
        Route::post('/change-password', [AuthController::class, 'changePassword']);
        Route::post('/recovery-code', [AuthController::class, 'recoveryCode']);
    });
});

// ── اتاق‌ها، فایل‌ها، سخنران‌ها، تایمر و ضبط (مالک) ──────────────────────
Route::middleware('mas.auth')->prefix('rooms')->group(function (): void {
    Route::get('/', [RoomController::class, 'index']);
    Route::post('/', [RoomController::class, 'store']);
    Route::get('/{roomId}', [RoomController::class, 'show']);
    Route::put('/{roomId}', [RoomController::class, 'update']);
    Route::delete('/{roomId}', [RoomController::class, 'destroy']);
    Route::post('/{roomId}/rotate-public-token', [RoomController::class, 'rotatePublicToken']);
    Route::get('/{roomId}/qr', [RoomController::class, 'qr']);

    Route::post('/{roomId}/files', [RoomController::class, 'uploadFile']);
    Route::post('/{roomId}/files/{fileId}/review', [RoomController::class, 'reviewFile']);
    Route::delete('/{roomId}/files/{fileId}', [RoomController::class, 'deleteFile']);
    Route::get('/{roomId}/files/{fileId}/download', [RoomController::class, 'download']);
    Route::get('/{roomId}/files/{fileId}/play', [RoomController::class, 'play']);
    Route::get('/{roomId}/report/pdf', [RoomController::class, 'reportPdf']);
    Route::post('/{roomId}/reactions/toggle', [RoomController::class, 'toggleReactions']);

    Route::post('/{roomId}/speakers', [SpeakerController::class, 'store']);
    Route::put('/{roomId}/speakers/{speakerId}', [SpeakerController::class, 'update']);
    Route::delete('/{roomId}/speakers/{speakerId}', [SpeakerController::class, 'destroy']);
    Route::post('/{roomId}/speakers/reorder', [SpeakerController::class, 'reorder']);
    Route::post('/{roomId}/speakers/{speakerId}/rotate-code', [SpeakerController::class, 'rotateCode']);
    Route::post('/{roomId}/speakers/{speakerId}/unfreeze', [SpeakerController::class, 'unfreeze']);
    Route::post('/{roomId}/reset-all', [SpeakerController::class, 'resetAll']);

    Route::get('/{roomId}/timer/state', [TimerController::class, 'state']);
    Route::post('/{roomId}/timer/action', [TimerController::class, 'action']);

    Route::post('/{roomId}/recording/start', [RecordingController::class, 'start']);
    Route::get('/{roomId}/recording/status', [RecordingController::class, 'status']);
    Route::post('/{roomId}/recording/chunk', [RecordingController::class, 'chunk']);
    Route::post('/{roomId}/recording/finish', [RecordingController::class, 'finish']);
});

// ── نمای عمومی تماشاگران ─────────────────────────────────────────────────
Route::prefix('public/{token}')->group(function (): void {
    Route::get('/state', [PublicController::class, 'state']);
    Route::get('/files/{fileId}', [PublicController::class, 'file']);
    Route::get('/qr', [PublicController::class, 'qr']);
    Route::post('/reactions', [PublicController::class, 'sendReaction']);
    Route::get('/reactions', [PublicController::class, 'recentReactions']);
    Route::get('/report/pdf', [PublicController::class, 'reportPdf']);

    // ── دستگاه سخنران (ورود با کد ۴کاراکتری) ──
    Route::post('/speaker/enter', [SpeakerAccessController::class, 'enter']);
    Route::middleware('mas.speaker')->prefix('speaker')->group(function (): void {
        Route::post('/heartbeat', [SpeakerAccessController::class, 'heartbeat']);
        Route::post('/leave', [SpeakerAccessController::class, 'leave']);
        Route::post('/recording/start', [SpeakerAccessController::class, 'recordingStart']);
        Route::post('/recording/chunk', [SpeakerAccessController::class, 'recordingChunk']);
        Route::post('/recording/finish', [SpeakerAccessController::class, 'recordingFinish']);
        Route::post('/files', [SpeakerAccessController::class, 'uploadFile']);
    });
});

// ── پنل مدیریت ───────────────────────────────────────────────────────────
Route::middleware(['mas.auth', 'mas.admin'])->prefix('admin')->group(function (): void {
    Route::get('/stats', [AdminController::class, 'stats']);
    Route::get('/users', [AdminController::class, 'users']);
    Route::post('/users/{userId}/toggle-active', [AdminController::class, 'toggleUserActive']);
    Route::get('/rooms', [AdminController::class, 'rooms']);
    Route::get('/audit-logs', [AdminController::class, 'auditLogs']);
});
