import React, { useEffect, useState } from 'react';

export interface FloatingItem {
  id: string;
  emoji: string;
  leftOffset: number; // درصد افقی 5% تا 85%
}

interface FloatingReactionsProps {
  reactions: Array<{ id: string; emoji: string }>;
}

const EMOJI_MAP: Record<string, string> = {
  heart: '❤️',
  clap: '👏',
  like: '👍',
  fire: '🔥',
  star: '⭐',
};

export const FloatingReactions: React.FC<FloatingReactionsProps> = ({ reactions }) => {
  const [activeItems, setActiveItems] = useState<FloatingItem[]>([]);

  useEffect(() => {
    if (!reactions || reactions.length === 0) return;

    // اضافه کردن آیتم‌های جدید بدون تکرار
    setActiveItems((prev) => {
      const existingIds = new Set(prev.map((i) => i.id));
      const newItems: FloatingItem[] = [];

      for (const r of reactions) {
        if (!existingIds.has(r.id)) {
          newItems.push({
            id: r.id,
            emoji: EMOJI_MAP[r.emoji] || '❤️',
            leftOffset: Math.floor(Math.random() * 75) + 10,
          });
        }
      }

      if (newItems.length === 0) return prev;
      return [...prev, ...newItems].slice(-35); // حداکثر ۳۵ تا در صفحه
    });
  }, [reactions]);

  // انقضای تدریجی واکنش‌ها بعد از ۲.۵ ثانیه انیمیشن
  useEffect(() => {
    if (activeItems.length === 0) return;
    const timer = setTimeout(() => {
      setActiveItems((prev) => prev.slice(1));
    }, 2500);
    return () => clearTimeout(timer);
  }, [activeItems]);

  return (
    <div className="pointer-events-none fixed inset-0 z-50 overflow-hidden">
      {activeItems.map((item) => (
        <div
          key={item.id}
          className="absolute bottom-16 animate-float-up text-3xl select-none"
          style={{
            left: `${item.leftOffset}%`,
          }}
        >
          {item.emoji}
        </div>
      ))}
    </div>
  );
};
