<?php

namespace App\Support;

use Exception;

/** بازهٔ Range از نظر نحوی معتبر است ولی خارج از اندازهٔ شیء قرار دارد (پاسخ ۴۱۶). */
class RangeNotSatisfiable extends Exception
{
}
