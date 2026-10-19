import { ChangeDetectionStrategy, Component, ElementRef, afterNextRender, inject, input, output } from '@angular/core';

@Component({
  selector: 'app-confirm-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '(document:keydown.escape)': 'cancel.emit()' },
  template: `
    <div class="overlay" (click)="cancel.emit()"></div>
    <div class="dialog" role="alertdialog" aria-modal="true" [attr.aria-labelledby]="'confirm-title'">
      <div class="dialog__body">
        <h2 id="confirm-title">{{ title() }}</h2>
        <p class="muted">{{ message() }}</p>
      </div>
      <div class="dialog__footer">
        <button type="button" class="btn btn-secondary" (click)="cancel.emit()" data-autofocus>Cancel</button>
        <button type="button" class="btn" [class.btn-danger]="danger()" [class.btn-primary]="!danger()"
                [disabled]="busy()" (click)="confirm.emit()">
          @if (busy()) {
            <span class="spinner" aria-hidden="true"></span>
          }
          {{ confirmLabel() }}
        </button>
      </div>
    </div>
  `,
})
export class ConfirmDialog {
  readonly title = input.required<string>();
  readonly message = input.required<string>();
  readonly confirmLabel = input('Confirm');
  readonly danger = input(false);
  readonly busy = input(false);
  readonly confirm = output<void>();
  readonly cancel = output<void>();

  constructor() {
    const host: ElementRef<HTMLElement> = inject(ElementRef);
    afterNextRender(() => host.nativeElement.querySelector<HTMLElement>('[data-autofocus]')?.focus());
  }
}
