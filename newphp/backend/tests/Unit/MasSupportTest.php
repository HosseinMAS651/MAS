<?php

namespace Tests\Unit;

use App\Support\Mas;
use PHPUnit\Framework\TestCase;

class MasSupportTest extends TestCase
{
    public function test_username_key_normalizes_case_and_separators(): void
    {
        $this->assertSame('aliرضa', Mas::usernameToKey('Ali رضa'));
        $this->assertSame('username', Mas::usernameToKey('User_Name'));
        $this->assertSame('username', Mas::usernameToKey('user-name'));
        $this->assertSame('username', Mas::usernameToKey(' user name '));
    }

    public function test_username_key_can_collapse_to_empty(): void
    {
        // مبنای رفع B-11 در لایهٔ ثبت‌نام: چنین نام‌هایی باید رد شوند.
        $this->assertSame('', Mas::usernameToKey('___'));
        $this->assertSame('', Mas::usernameToKey('---'));
        $this->assertSame('', Mas::usernameToKey('   '));
    }

    public function test_sanitize_filename_blocks_traversal_and_separators(): void
    {
        $this->assertSame('file.txt', Mas::sanitizeFilename('../../file.txt'));
        $this->assertSame('ab.txt', Mas::sanitizeFilename('a/b\\.txt'));
        $this->assertSame('file', Mas::sanitizeFilename('...'));
        $this->assertSame('گزارش نهایی.pdf', Mas::sanitizeFilename('گزارش نهایی.pdf'));
    }

    public function test_format_ms_to_min_sec(): void
    {
        $this->assertSame('00:00', Mas::formatMsToMinSec(0));
        $this->assertSame('01:05', Mas::formatMsToMinSec(65_000));
        $this->assertSame('10:00', Mas::formatMsToMinSec(600_000));
    }
}
