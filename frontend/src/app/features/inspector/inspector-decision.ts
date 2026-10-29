import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';

import { FirewallResult } from '../../core/models/api.models';
import { StatusBadge } from '../../shared/components/status-badge';
import { DurationPipe } from '../../shared/pipes/format.pipes';

const DECISION_TEXT: Record<string, string> = {
  ALLOWED: 'No sensitive data found. Processing allowed.',
  REDACTED: 'Sensitive values replaced with tokens before AI.',
  LOCAL_ONLY: 'Local model only. Nothing sent to the cloud.',
  BLOCKED: 'AI processing not permitted. Nothing was sent.',
  PROCESSING_FAILED: 'Failed closed. Nothing was sent.',
};

/** Final decision banner and warnings, shared by the Inspector summary and the details page. */
@Component({
  selector: 'app-inspector-decision',
  imports: [LucideDynamicIcon, StatusBadge, DurationPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let r = result();
    <section class="card decision decision--{{ r.decision.toLowerCase() }}" aria-live="polite">
      <div class="decision__main">
        <div class="decision__label">
          <span class="section-title">Final decision</span>
          <app-status-badge [value]="r.decision" [uppercase]="true" [strong]="true" />
        </div>
        <p class="decision__text">{{ decisionText() }}</p>
      </div>
      <dl class="decision__facts">
        <div><dt>Authorized destination</dt><dd><app-status-badge [value]="r.authorized_destination" /></dd></div>
        <div><dt>Processing status</dt><dd><app-status-badge [value]="r.status" /></dd></div>
        <div><dt>Total duration</dt><dd class="mono">{{ r.latency.total_ms | duration }}</dd></div>
        <div><dt>Request ID</dt><dd class="mono" [title]="r.request_id">{{ r.request_id.slice(0, 8) }}</dd></div>
      </dl>
    </section>

    @for (w of r.warnings; track $index) {
      <div class="alert alert-warning" role="status">
        <svg class="icon" lucideIcon="triangle-alert" aria-hidden="true"></svg>
        <span>{{ w }}</span>
      </div>
    }
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      gap: var(--s-4);
      min-width: 0;
    }
    .decision {
      display: flex;
      flex-wrap: wrap;
      gap: var(--s-4) var(--s-6);
      justify-content: space-between;
      padding: var(--s-5);
      border-left: 4px solid var(--decision-color, var(--c-border));
    }
    .decision--allowed {
      --decision-color: var(--c-success);
    }
    .decision--redacted {
      --decision-color: var(--c-blue);
    }
    .decision--local_only {
      --decision-color: #5b8fd0;
    }
    .decision--blocked {
      --decision-color: var(--c-error);
    }
    .decision--processing_failed {
      --decision-color: var(--c-warning);
    }
    .decision__main {
      display: flex;
      flex-direction: column;
      gap: var(--s-2);
      flex: 1 1 260px;
    }
    .decision__label {
      display: flex;
      align-items: center;
      gap: var(--s-3);
    }
    .decision__text {
      font-size: var(--fs-sm);
      color: var(--c-text-2);
    }
    .decision__facts {
      display: grid;
      flex: 0 1 auto;
      min-width: 0;
      grid-template-columns: repeat(2, auto);
      gap: var(--s-3) var(--s-6);
      margin: 0;
      font-size: var(--fs-sm);

      dt {
        color: var(--c-text-2);
        font-size: var(--fs-xs);
      }

      dd {
        margin: 2px 0 0;
      }
    }
    @media (max-width: 560px) {
      .decision__facts {
        grid-template-columns: minmax(0, 1fr);
      }
    }
  `,
})
export class InspectorDecision {
  readonly result = input.required<FirewallResult>();
  protected readonly decisionText = computed(() => DECISION_TEXT[this.result().decision] ?? '');
}
