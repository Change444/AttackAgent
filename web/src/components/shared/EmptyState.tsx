export default function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center py-12">
      <div className="text-center">
        <p className="text-sm text-slate-dark">{message}</p>
      </div>
    </div>
  );
}