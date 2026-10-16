#!/bin/sh
# آماده‌سازی کانتینر MAS: فایل env، کلیدها، مهاجرت دیتابیس و کش کانفیگ.
set -e
cd /var/www/html

if [ ! -f .env ]; then
    cp .env.example .env
fi

# کلید برنامه (برای Crypt کدهای سخنران) و کلید HMAC نشست‌ها؛ فقط وقتی خالی‌اند
# ساخته می‌شوند. در production واقعی هر دو را از بیرون (compose/secret) بدهید.
if ! grep -q '^APP_KEY=base64:' .env; then
    php artisan key:generate --force
fi
if ! grep -q '^MAS_SECRET_KEY=.\{32,\}' .env; then
    SECRET=$(php -r 'echo bin2hex(random_bytes(32));')
    if grep -q '^MAS_SECRET_KEY=' .env; then
        sed -i "s|^MAS_SECRET_KEY=.*|MAS_SECRET_KEY=${SECRET}|" .env
    else
        echo "MAS_SECRET_KEY=${SECRET}" >> .env
    fi
fi

# منتظر دیتابیس می‌مانیم و مهاجرت‌ها را اجرا می‌کنیم (idempotent).
php artisan migrate --force

php artisan config:cache

exec "$@"
