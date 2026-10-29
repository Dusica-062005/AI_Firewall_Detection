import { Pipe, PipeTransform } from '@angular/core';

// Words that stay in capitals once an enum is turned into text.
const ACRONYMS = new Set(['id', 'ai', 'sms', 'phi', 'pii', 'ok', 'api', 'ip', 'url', 'gpu', 'cpu', 'dob', 'ssn', 'iban']);

/** "LOCAL_ONLY" -> "Local only", "PATIENT_ID" -> "Patient ID", "COMPLETED_WITH_WARNINGS" -> "Completed with warnings". */
export function humanize(value: string | null | undefined): string {
  if (!value) {
    return '';
  }
  const words = value.replace(/[_-]+/g, ' ').trim().toLowerCase().split(/\s+/);
  const text = words.map((w) => (ACRONYMS.has(w) ? w.toUpperCase() : w)).join(' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Byte counts as "512 KB" or "1 MB". */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) {
    return '-';
  }
  if (bytes < 1024) {
    return `${bytes} bytes`;
  }
  const kb = bytes / 1024;
  return kb < 1024 ? `${+kb.toFixed(1)} KB` : `${+(kb / 1024).toFixed(1)} MB`;
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

@Pipe({ name: 'bytes' })
export class BytesPipe implements PipeTransform {
  transform(value: number | null | undefined): string {
    return formatBytes(value);
  }
}

@Pipe({ name: 'duration' })
export class DurationPipe implements PipeTransform {
  transform(value: number | null | undefined): string {
    return formatDuration(value);
  }
}
