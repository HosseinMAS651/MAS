<?php

namespace App\Services;

use Illuminate\Support\Facades\Cache;

/**
 * واکنش‌های زندهٔ تماشاگران (معادل reaction_service.py).
 * نسخهٔ Python حافظه‌ای و تک‌پروسه‌ای بود؛ در PHP-FPM چندپروسه‌ای، به‌جای آن
 * از Cache اشتراکی (Redis در استقرار Docker) استفاده می‌شود تا همهٔ ورکرها
 * یک وضعیت ببینند. TTL آیتم‌ها ۱۲ ثانیه و سقف لیست هر اتاق ۱۰۰۰ است.
 */
class ReactionService
{
    private const TTL_SECONDS = 12;

    private const MAX_RECENT_PER_ROOM = 1000;

    private const VALID_EMOJIS = ['heart', 'clap', 'like', 'fire', 'star'];

    public function isEnabled(int $roomId): bool
    {
        return (bool) Cache::get($this->enabledKey($roomId), true);
    }

    public function setEnabled(int $roomId, bool $enabled): void
    {
        Cache::forever($this->enabledKey($roomId), $enabled);
    }

    /** @return array{id: string, emoji: string, created_at: float}|null */
    public function addReaction(int $roomId, string $emoji): ?array
    {
        if (! $this->isEnabled($roomId)) {
            return null;
        }
        if (! in_array($emoji, self::VALID_EMOJIS, true)) {
            $emoji = 'heart';
        }
        $now = microtime(true);
        $item = [
            'id' => substr(bin2hex(random_bytes(8)), 0, 10),
            'emoji' => $emoji,
            'created_at' => $now,
        ];

        $items = $this->prune($this->items($roomId), $now);
        $items[] = $item;
        if (count($items) > self::MAX_RECENT_PER_ROOM) {
            $items = array_slice($items, -self::MAX_RECENT_PER_ROOM);
        }
        Cache::put($this->itemsKey($roomId), $items, self::TTL_SECONDS + 30);

        $totals = $this->getTotals($roomId);
        $totals[$emoji] = ($totals[$emoji] ?? 0) + 1;
        Cache::forever($this->totalsKey($roomId), $totals);

        return $item;
    }

    /** @return list<array{id: string, emoji: string, created_at: float}> */
    public function getRecent(int $roomId, float $sinceSeconds = 3.0): array
    {
        $now = microtime(true);
        $cutoff = $now - $sinceSeconds;

        return array_values(array_filter(
            $this->items($roomId),
            fn (array $item) => $item['created_at'] >= $cutoff,
        ));
    }

    /** @return array<string, int> */
    public function getTotals(int $roomId): array
    {
        return Cache::get($this->totalsKey($roomId), []);
    }

    /** @return list<array{id: string, emoji: string, created_at: float}> */
    private function items(int $roomId): array
    {
        return Cache::get($this->itemsKey($roomId), []);
    }

    /** @param list<array{created_at: float}> $items */
    private function prune(array $items, float $now): array
    {
        $cutoff = $now - self::TTL_SECONDS;

        return array_values(array_filter($items, fn (array $i) => $i['created_at'] >= $cutoff));
    }

    private function itemsKey(int $roomId): string
    {
        return "mas:reactions:{$roomId}:items";
    }

    private function totalsKey(int $roomId): string
    {
        return "mas:reactions:{$roomId}:totals";
    }

    private function enabledKey(int $roomId): string
    {
        return "mas:reactions:{$roomId}:enabled";
    }
}
