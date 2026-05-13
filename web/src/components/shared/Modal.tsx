export default function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-base-900/60 backdrop-blur-sm" onClick={onClose} />

      {/* Modal panel */}
      <div className="relative bg-base-800 rounded-lg border border-amber/30 shadow-xl max-w-md w-full mx-4 animate-fade-in">
        <div className="px-4 py-3 border-b border-base-600/30 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-amber">{title}</h3>
          <button onClick={onClose} className="text-slate-dark hover:text-slate text-xs">Close</button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

export function ConfirmModal({ title, message, onConfirm, onCancel, confirmLabel = 'Confirm', danger = false }: {
  title: string;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
  confirmLabel?: string;
  danger?: boolean;
}) {
  return (
    <Modal title={title} onClose={onCancel}>
      <p className="text-sm text-base-50 mb-4">{message}</p>
      <div className="flex gap-3 justify-end">
        <button
          onClick={onCancel}
          className="px-4 py-2 rounded text-xs font-medium bg-base-700 text-slate hover:text-base-50 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={onConfirm}
          className={`px-4 py-2 rounded text-xs font-medium transition-colors ${
            danger
              ? 'bg-danger text-base-900 hover:bg-danger-light'
              : 'bg-amber text-base-900 hover:bg-amber-light'
          }`}
        >
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}