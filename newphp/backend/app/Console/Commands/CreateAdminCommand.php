<?php

namespace App\Console\Commands;

use App\Models\User;
use App\Services\SecurityService;
use App\Support\Mas;
use Illuminate\Console\Command;

/**
 * معادل scripts/create_admin.py: ارتقای یک حساب ثبت‌نام‌شده به مدیر سیستم.
 * ادمین هرگز از مسیر ثبت‌نام عمومی ساخته نمی‌شود؛ کاربر باید اول ثبت‌نام کند.
 */
class CreateAdminCommand extends Command
{
    protected $signature = 'mas:create-admin {username} {--password=}';

    protected $description = 'ارتقای کاربر موجود به مدیر سیستم و بازنشانی رمز او';

    public function handle(SecurityService $security): int
    {
        $username = Mas::normalizeUsername((string) $this->argument('username'));
        $password = (string) ($this->option('password') ?: $this->secret('Admin password'));
        if (mb_strlen($password) < 8) {
            $this->error('Password must be at least 8 characters.');

            return self::FAILURE;
        }

        $user = User::query()
            ->where('username_key', Mas::usernameToKey($username))
            ->first();
        if (! $user) {
            $this->error('User does not exist; register the account first, then rerun this tool.');

            return self::FAILURE;
        }

        $user->role = 'admin';
        $user->is_active = true;
        $user->failed_login_count = 0;
        $user->locked_until_ms = 0;
        $user->password_hash = $security->hashPassword($password);
        $user->save();

        $this->info('Admin account updated.');

        return self::SUCCESS;
    }
}
