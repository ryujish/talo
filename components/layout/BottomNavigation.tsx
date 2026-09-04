'use client';

import { Clock3, House, Lightbulb, type LucideIcon, User } from 'lucide-react';

const items: { title: string; icon: LucideIcon }[] = [
  { title: 'Think', icon: House },
  { title: 'Journey', icon: Clock3 },
  { title: 'Insight', icon: Lightbulb },
  { title: 'Profile', icon: User },
];

export default function BottomNavigation() {
  return (
    <nav className="fixed inset-x-0 bottom-0 border-t bg-white">
      <div className="mx-auto flex max-w-4xl justify-around py-3">
        {items.map(({ title, icon: Icon }) => (
          <button key={title} className="flex flex-col items-center gap-1 text-xs">
            <Icon size={20} />
            {title}
          </button>
        ))}
      </div>
    </nav>
  );
}
