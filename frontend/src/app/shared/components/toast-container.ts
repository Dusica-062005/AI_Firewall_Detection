import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';

import { NotificationService } from '../../core/services/notification.service';

const ICONS = { success: 'circle-check', error: 'circle-x', info: 'info', warning: 'triangle-alert' } as const;

@Component({
  selector: 'app-toast-container',
  imports: [LucideDynamicIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="toasts" aria-live="polite">
      @for (notice of notifications.notices(); track notice.id) {
        <div class="alert alert-{{ notice.kind }} toast" role="status">
          <svg class="icon" [lucideIcon]="icons[notice.kind]" aria-hidden="true"></svg>
          <span class="toast__text">{{ notice.message }}</span>
          <button type="button" class="btn btn-ghost btn-icon btn-sm" aria-label="Dismiss notification"
                  (click)="notifications.dismiss(notice.id)">
            <svg class="icon" lucideIcon="x" aria-hidden="true"></svg>
          </button>
        </div>
      }
    </div>
  `,
  styles: `
    .toasts {
      position: fixed;
      right: 16px;
      bottom: 16px;
      z-index: 70;
      display: flex;
      flex-direction: column;
      gap: 8px;
      width: min(380px, calc(100vw - 32px));
    }
    .toast {
      align-items: center;
      box-shadow: var(--shadow-overlay);
    }
    .toast__text {
      flex: 1;
    }
  `,
})
export class ToastContainer {
  protected readonly notifications = inject(NotificationService);
  protected readonly icons = ICONS;
}
