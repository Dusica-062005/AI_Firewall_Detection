import { Injectable, signal } from '@angular/core';

export type NoticeKind = 'success' | 'error' | 'info' | 'warning';

export interface Notice {
  id: number;
  kind: NoticeKind;
  message: string;
}

/** Transient toast notifications. Messages never contain transcript content. */
@Injectable({ providedIn: 'root' })
export class NotificationService {
  private nextId = 1;
  readonly notices = signal<Notice[]>([]);

  show(kind: NoticeKind, message: string, timeoutMs = 5000): void {
    const notice = { id: this.nextId++, kind, message };
    this.notices.update((list) => [...list.slice(-3), notice]);
    if (timeoutMs > 0) {
      setTimeout(() => this.dismiss(notice.id), timeoutMs);
    }
  }

  success(message: string): void {
    this.show('success', message);
  }

  error(message: string): void {
    this.show('error', message, 8000);
  }

  dismiss(id: number): void {
    this.notices.update((list) => list.filter((n) => n.id !== id));
  }
}
