import { getStatusColor } from '../../utils/constants';

export default function StatusBadge({ status, domain = 'project' }: { status: string; domain?: 'project' | 'solver' | 'idea' | 'review' | 'intervention' | 'risk' }) {
  const colorClass = getStatusColor(domain, status);
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium ${colorClass}`}>
      {status}
    </span>
  );
}