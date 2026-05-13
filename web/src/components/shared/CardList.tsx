export default function CardList<T>({ items, render }: { items: T[]; render: (item: T) => React.ReactNode }) {
  if (items.length === 0) return <EmptyState message="No items found" />;
  return <div className="grid gap-4">{items.map(render)}</div>;
}

import EmptyState from './EmptyState';