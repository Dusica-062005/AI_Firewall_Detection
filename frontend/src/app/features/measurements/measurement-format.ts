/** Shared formatting for measured numbers. A missing number is never shown as 0. */

export function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? '-' : `${(value * 100).toFixed(1)}%`;
}

/** Signed percentage-point change, for run comparisons. */
export function delta(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '-';
  }
  const points = value * 100;
  return `${points > 0 ? '+' : ''}${points.toFixed(1)} pts`;
}

/** 'better' | 'worse' | 'same' for a change, where higher recall and lower leak rate are better. */
export function trend(value: number | null | undefined, higherIsBetter: boolean): 'better' | 'worse' | 'same' {
  if (value === null || value === undefined || value === 0) {
    return 'same';
  }
  return value > 0 === higherIsBetter ? 'better' : 'worse';
}

export function score(value: number | null | undefined): string {
  return value === null || value === undefined ? '-' : value.toFixed(2);
}
