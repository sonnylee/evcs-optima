import type { ButtonHTMLAttributes } from 'react';

type Variant = 'primary' | 'secondary' | 'ghost';

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

const VARIANT_CLASSES: Record<Variant, string> = {
  primary:
    'bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 text-white',
  secondary:
    'bg-white border border-slate-300 hover:bg-slate-100 disabled:opacity-50 text-slate-800',
  ghost:
    'bg-transparent hover:bg-slate-100 disabled:opacity-50 text-slate-700',
};

export function Button({
  variant = 'primary',
  className = '',
  ...rest
}: Props) {
  return (
    <button
      className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${VARIANT_CLASSES[variant]} ${className}`}
      {...rest}
    />
  );
}
