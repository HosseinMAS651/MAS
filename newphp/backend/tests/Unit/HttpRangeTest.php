<?php

namespace Tests\Unit;

use App\Support\HttpRange;
use App\Support\RangeNotSatisfiable;
use PHPUnit\Framework\TestCase;

/** رگرسیون B-04: پارس Range تک‌بخشی مثل parse_single_range نسخهٔ Python. */
class HttpRangeTest extends TestCase
{
    public function test_no_header_means_full_body(): void
    {
        $this->assertNull(HttpRange::parseSingle(null, 1000));
        $this->assertNull(HttpRange::parseSingle('', 1000));
    }

    public function test_simple_and_open_ended_ranges(): void
    {
        $this->assertSame([100, 199], HttpRange::parseSingle('bytes=100-199', 1000));
        $this->assertSame([900, 999], HttpRange::parseSingle('bytes=900-', 1000));
        $this->assertSame([0, 999], HttpRange::parseSingle('bytes=0-', 1000));
    }

    public function test_suffix_range_and_end_clamping(): void
    {
        $this->assertSame([950, 999], HttpRange::parseSingle('bytes=-50', 1000));
        $this->assertSame([0, 999], HttpRange::parseSingle('bytes=-5000', 1000));
        $this->assertSame([100, 999], HttpRange::parseSingle('bytes=100-99999', 1000));
    }

    public function test_multi_range_and_garbage_fall_back_to_full_body(): void
    {
        $this->assertNull(HttpRange::parseSingle('bytes=0-99,200-299', 1000));
        $this->assertNull(HttpRange::parseSingle('items=0-99', 1000));
        $this->assertNull(HttpRange::parseSingle('bytes=abc-def', 1000));
    }

    public function test_unsatisfiable_ranges_throw(): void
    {
        $this->expectException(RangeNotSatisfiable::class);
        HttpRange::parseSingle('bytes=1000-1099', 1000);
    }

    public function test_zero_suffix_is_unsatisfiable(): void
    {
        $this->expectException(RangeNotSatisfiable::class);
        HttpRange::parseSingle('bytes=-0', 1000);
    }
}
