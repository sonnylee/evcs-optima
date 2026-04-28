import type { ErrorDetail } from '../../types/evcs';

interface Props {
  errors: ErrorDetail[];
  onDismiss?: () => void;
}

export function ErrorBanner({ errors, onDismiss }: Props) {
  if (errors.length === 0) return null;
  return (
    <div className="rounded border border-red-300 bg-red-50 p-3 text-xs text-red-900">
      <div className="flex justify-between items-start mb-1">
        <strong>{errors.length} error{errors.length > 1 ? 's' : ''}</strong>
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="text-red-600 hover:text-red-800"
            aria-label="Dismiss errors"
          >
            ×
          </button>
        )}
      </div>
      <ul className="list-disc pl-4 space-y-0.5">
        {errors.map((e, i) => (
          <li key={`${e.code}-${e.field ?? ''}-${i}`}>
            <span className="font-mono">{e.code}</span>: {e.message}
            {e.field && <code className="ml-1 text-red-700">({e.field})</code>}
          </li>
        ))}
      </ul>
    </div>
  );
}
