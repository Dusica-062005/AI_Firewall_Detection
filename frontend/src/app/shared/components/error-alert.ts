import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';

import { ApiError } from '../../core/models/api.models';

@Component({
  selector: 'app-error-alert',
  imports: [LucideDynamicIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (error(); as err) {
      <div class="alert alert-error" role="alert">
        <svg class="icon" lucideIcon="circle-x" aria-hidden="true"></svg>
        <div class="stack" style="gap: 4px; flex: 1">
          <span class="alert__title">{{ title() }}</span>
          <span>{{ err.message }}</span>
          @for (detail of err.details; track $index) {
            <span class="text-xs">{{ detail }}</span>
          }
          @if (err.requestId) {
            <span class="text-xs mono">Request ID {{ err.requestId }}</span>
          }
        </div>
        @if (retryable()) {
          <button type="button" class="btn btn-secondary btn-sm" (click)="retry.emit()">
            <svg class="icon" lucideIcon="refresh-cw" aria-hidden="true"></svg>
            Retry
          </button>
        }
      </div>
    }
  `,
})
export class ErrorAlert {
  readonly error = input<ApiError | null>(null);
  readonly title = input('Request failed');
  readonly retryable = input(false);
  readonly retry = output<void>();
}
