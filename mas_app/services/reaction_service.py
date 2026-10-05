"""سرویس مدیریت واکنش‌های زنده و برخط تماشاگران (Floating Reactions) به صورت حافظه‌ای و سبک."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class ReactionItem:
    id: str
    emoji: str
    created_at: float


class ReactionManager:
    """نگهداری سبک واکنش‌ها با انقضای خودکار ۱۰ ثانیه‌ای جهت انیمیشن‌های روان تماشاگران."""

    def __init__(self, ttl_seconds: float = 12.0, max_recent_per_room: int = 1_000) -> None:
        self.ttl = ttl_seconds
        self.max_recent_per_room = max_recent_per_room
        # room_id -> list[ReactionItem]
        self._reactions: dict[int, list[ReactionItem]] = defaultdict(list)
        # room_id -> dict[emoji, count]
        self._totals: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # room_id -> bool
        self._enabled: dict[int, bool] = defaultdict(lambda: True)

    def is_enabled(self, room_id: int) -> bool:
        return self._enabled[room_id]

    def set_enabled(self, room_id: int, enabled: bool) -> None:
        self._enabled[room_id] = enabled

    def add_reaction(self, room_id: int, emoji: str) -> ReactionItem | None:
        if not self._enabled[room_id]:
            return None
        valid_emojis = {"heart", "clap", "like", "fire", "star"}
        if emoji not in valid_emojis:
            emoji = "heart"

        now = time.time()
        self._cleanup(room_id, now)

        item = ReactionItem(
            id=uuid.uuid4().hex[:10],
            emoji=emoji,
            created_at=now,
        )
        self._reactions[room_id].append(item)
        if len(self._reactions[room_id]) > self.max_recent_per_room:
            del self._reactions[room_id][:-self.max_recent_per_room]
        self._totals[room_id][emoji] += 1
        return item

    def get_recent(self, room_id: int, since_seconds: float = 3.0) -> list[dict[str, str | float]]:
        now = time.time()
        self._cleanup(room_id, now)
        items = self._reactions[room_id]
        cutoff = now - since_seconds
        return [
            {"id": item.id, "emoji": item.emoji, "created_at": item.created_at}
            for item in items
            if item.created_at >= cutoff
        ]

    def get_totals(self, room_id: int) -> dict[str, int]:
        return dict(self._totals[room_id])

    def _cleanup(self, room_id: int, now: float) -> None:
        cutoff = now - self.ttl
        self._reactions[room_id] = [r for r in self._reactions[room_id] if r.created_at >= cutoff]


reaction_manager = ReactionManager()
