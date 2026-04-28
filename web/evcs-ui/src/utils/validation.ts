export const STEP_KW = 25;
export const MAX_REQUIRED_MIN = 0;
export const MAX_REQUIRED_MAX = 600;
export const REC_BD_MIN = 1;
export const REC_BD_MAX = 12;
export const POWER_MIN_PER_MODULE = 50;
export const POWER_MAX_PER_MODULE = 100;

export function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

export function roundToStep(v: number, step = STEP_KW): number {
  return Math.round(v / step) * step;
}

export function clampMaxRequired(v: number): number {
  return roundToStep(clamp(v, MAX_REQUIRED_MIN, MAX_REQUIRED_MAX));
}
