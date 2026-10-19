import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';

import { ProcessingStep, StepStatus } from '../../core/models/api.models';
import { DurationPipe, HumanizePipe } from '../../shared/pipes/format.pipes';

const ICONS: Record<StepStatus, string> = {
  COMPLETED: 'circle-check',
  WARNING: 'triangle-alert',
  BLOCKED: 'shield-ban',
  FAILED: 'circle-x',
  SKIPPED: 'circle-minus',
};

/** Received -> Analyzed -> Policy evaluated -> Protected -> Local AI / Cloud -> Audited */
@Component({
  selector: 'app-processing-steps',
  imports: [LucideDynamicIcon, DurationPipe, HumanizePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <ol class="steps" aria-label="Processing sequence">
      @for (step of steps(); track step.key; let i = $index) {
        <li class="step step--{{ step.status.toLowerCase() }}">
          <div class="step__head">
            <span class="step__icon"><svg class="icon" [lucideIcon]="icons[step.status]" aria-hidden="true"></svg></span>
            <span class="step__label">{{ step.label }}</span>
          </div>
          <span class="step__status">{{ step.status | humanize }}@if (step.duration_ms !== null) { &middot; {{ step.duration_ms | duration }} }</span>
          <span class="step__detail">{{ step.detail }}</span>
        </li>
      }
    </ol>
  `,
  styles: `
    .steps {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 0;
      border: 1px solid var(--c-border);
      border-radius: var(--r-md);
      overflow: hidden;
    }
    :host {
      display: block;
      container-type: inline-size;
    }
    @container (max-width: 900px) {
      .steps {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
    }
    @container (max-width: 480px) {
      .steps {
        grid-template-columns: minmax(0, 1fr);
      }
    }
    .step {
      display: flex;
      flex-direction: column;
      gap: 2px;
      padding: 10px 12px;
      border-right: 1px solid var(--c-border);
      border-bottom: 1px solid var(--c-border);
      border-top: 3px solid var(--step-color);
      background: var(--c-surface);
      min-width: 0;
      margin-bottom: -1px;
    }
    .step__head {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .step__icon {
      color: var(--step-color);
      display: inline-flex;
    }
    .step__label {
      font-weight: 600;
      font-size: var(--fs-sm);
    }
    .step__status {
      font-size: var(--fs-xs);
      color: var(--step-color);
      font-weight: 600;
    }
    .step__detail {
      font-size: var(--fs-xs);
      color: var(--c-text-2);
      overflow-wrap: anywhere;
    }
    .step--completed {
      --step-color: var(--c-success);
    }
    .step--warning {
      --step-color: var(--c-warning);
    }
    .step--blocked,
    .step--failed {
      --step-color: var(--c-error);
    }
    .step--skipped {
      --step-color: var(--c-text-2);
      background: var(--c-surface-muted);
    }
  `,
})
export class ProcessingSteps {
  readonly steps = input.required<ProcessingStep[]>();
  protected readonly icons = ICONS;
}
