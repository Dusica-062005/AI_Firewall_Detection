import { Injectable, signal } from '@angular/core';

const STORAGE_KEY = 'maf.adminKey';

/**
 * Holds the optional administrator key for policy mutations. Kept in sessionStorage
 * only (cleared when the tab closes) and never displayed after entry.
 */
@Injectable({ providedIn: 'root' })
export class AdminKeyService {
  private readonly key = signal<string>(this.read());
  readonly hasKey = () => this.key().length > 0;

  value(): string {
    return this.key();
  }

  set(value: string): void {
    const trimmed = value.trim();
    this.key.set(trimmed);
    try {
      if (trimmed) {
        sessionStorage.setItem(STORAGE_KEY, trimmed);
      } else {
        sessionStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // Storage unavailable: the key stays in memory for this session only.
    }
  }

  private read(): string {
    try {
      return sessionStorage.getItem(STORAGE_KEY) ?? '';
    } catch {
      return '';
    }
  }
}
