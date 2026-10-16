# ── MAS backend: PHP 8.3 FPM + Laravel 12 ───────────────────────────────
FROM php:8.3-fpm-bookworm

# افزونه‌های لازم: pgsql (دیتابیس)، gd+mbstring (گزارش PDF با mPDF)،
# zip/bcmath/intl (نیازهای Laravel و mPDF)، redis (کش واکنش‌ها).
RUN apt-get update && apt-get install -y --no-install-recommends \
        git unzip libpq-dev libpng-dev libjpeg-dev libfreetype6-dev \
        libzip-dev libicu-dev libonig-dev \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install -j"$(nproc)" pdo_pgsql mbstring gd zip bcmath intl pcntl opcache \
    && pecl install redis \
    && docker-php-ext-enable redis \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=composer:2 /usr/bin/composer /usr/bin/composer

# سقف‌های آپلود هماهنگ با MAS_MAX_UPLOAD_MB (پیش‌فرض ۵۰ مگابایت).
RUN { \
      echo 'upload_max_filesize=64M'; \
      echo 'post_max_size=66M'; \
      echo 'memory_limit=512M'; \
      echo 'max_execution_time=180'; \
    } > /usr/local/etc/php/conf.d/mas.ini

WORKDIR /var/www/html

# اول فقط وابستگی‌ها (کش لایهٔ Docker)، بعد کل کد.
# توجه: composer.lock عمداً در ریپو نیست؛ هنگام بیلد ساخته/استفاده می‌شود.
COPY composer.json ./
RUN composer install --no-dev --no-scripts --no-autoloader --prefer-dist

COPY . .
RUN composer dump-autoload --optimize \
    && mkdir -p storage/app/uploads storage/framework/cache storage/framework/sessions \
             storage/framework/views storage/logs bootstrap/cache \
    && chown -R www-data:www-data storage bootstrap/cache

COPY docker-entrypoint.sh /usr/local/bin/mas-entrypoint
RUN chmod +x /usr/local/bin/mas-entrypoint

EXPOSE 9000
ENTRYPOINT ["mas-entrypoint"]
CMD ["php-fpm"]
