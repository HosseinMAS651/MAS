<?php

namespace App\Http\Middleware;

use App\Exceptions\ForbiddenError;
use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/** معادل get_current_admin در deps.py؛ بعد از AuthenticateMas اجرا می‌شود. */
class EnsureAdmin
{
    public function handle(Request $request, Closure $next): Response
    {
        $user = $request->attributes->get('mas_user');
        if (! $user || $user->role !== 'admin') {
            throw new ForbiddenError('دسترسی به این بخش نیازمند سطح کاربری مدیر (Admin) است.');
        }

        return $next($request);
    }
}
