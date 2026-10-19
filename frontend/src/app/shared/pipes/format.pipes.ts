import { Pipe, PipeTransform } from '@angular/core';

/** "LOCAL_ONLY" -> "Local only", "COMPLETED_WITH_WARNINGS" -> "Completed with warnings". */
export function humanize(value: string | null | undefined): string {
  if (!value) {
    return '';
  }
  const text = value.replace(/[_-]+/g, ' ').trim().toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) {
    return '-';
  }
  if (ms < 1) {
    return '<1 ms';
  }
  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
}

@Pipe({ name: 'humanize' })
export class HumanizePipe implements PipeTransform {
  transform(value: string | null | undefined): string {
    return humanize(value);
  }
}

@Pipe({ name: 'duration' })
export class DurationPipe implements PipeTransform {
  transform(value: number | null | undefined): string {
    return formatDuration(value);
  }
}
