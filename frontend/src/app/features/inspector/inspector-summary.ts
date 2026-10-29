import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { LucideDynamicIcon } from '@lucide/angular';

import { FirewallResult } from '../../core/models/api.models';
import { StatusBadge } from '../../shared/components/status-badge';
import { HumanizePipe } from '../../shared/pipes/format.pipes';
import { InspectorDecision } from './inspector-decision';

/** The main outcome of a request on the Inspector page; everything else is on the details page. */
@Component({
  selector: 'app-inspector-summary',
  imports: [RouterLink, LucideDynamicIcon, StatusBadge, HumanizePipe, InspectorDecision],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let r = result();
    <app-inspector-decision [result]="r" />

    <section class="card">
      <div class="card-header">
        <h2><svg class="icon" lucideIcon="list-checks" aria-hidden="true"></svg>Key results</h2>
        <span class="card-header__meta">{{ r.operation === 'INSPECT' ? 'Inspection only' : 'Mode: ' + (r.mode | humanize) }}</span>
      </div>

      <div class="card-body highlights">
        <div class="highlight">
          <span class="section-title">Sensitive entities</span>
          <span class="highlight__value">{{ r.entities.length }}</span>
          @if (categories().length) {
            <div class="tag-list">
              @for (c of categories(); track c.type) {
                <span class="tag">{{ c.type | humanize }}{{ c.count > 1 ? ' ×' + c.count : '' }}</span>
              }
            </div>
          } @else {
            <span class="text-xs muted">None detected</span>
          }
        </div>

        <div class="highlight">
          <span class="section-title">Where it went</span>
          <div class="row wrap">
            @if (r.routing; as route) {
              <app-status-badge [value]="route.route" [label]="routeLabel()" />
            } @else {
              <app-status-badge [value]="r.authorized_destination" />
            }
          </div>
          <span class="text-xs muted">
            {{ r.outbound.reached_receiver ? 'Tokenized payload reached the mock CloudLink receiver.' : 'Nothing left the firewall.' }}
          </span>
        </div>

        <div class="highlight">
          <span class="section-title">Processing steps</span>
          <span class="highlight__value">{{ steps().completed }}<span class="highlight__of">/ {{ steps().total }}</span></span>
          <span class="text-xs muted">
            {{ steps().issues ? steps().issues + ' with warnings or blocks' : 'Completed' }}{{ steps().skipped ? ', ' + steps().skipped + ' skipped' : '' }}
          </span>
        </div>
      </div>

      @if (r.agent_view?.summary; as summary) {
        <div class="card-body agent">
          <span class="section-title">What the agent sees</span>
          <div class="text-block agent__text">{{ summary }}</div>
        </div>
      }

      <div class="card-footer">
        <span class="text-xs muted">Before and after text, entity table, policy evaluation, cloud handoff and audit record.</span>
        <a class="btn btn-primary" routerLink="/inspector/result">
          View full details
          <svg class="icon" lucideIcon="arrow-right" aria-hidden="true"></svg>
        </a>
      </div>
    </section>
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      gap: var(--s-4);
      min-width: 0;
    }
    .highlights {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: var(--s-4);
    }
    @media (max-width: 720px) {
      .highlights {
        grid-template-columns: minmax(0, 1fr);
      }
    }
    .highlight {
      display: flex;
      flex-direction: column;
      gap: var(--s-2);
      min-width: 0;
      padding: var(--s-4);
      border: 1px solid var(--c-border);
      border-radius: var(--r-md);
      background: var(--c-surface-muted);
    }
    .highlight__value {
      font-size: 24px;
      font-weight: 600;
      line-height: 1.2;
      font-variant-numeric: tabular-nums;
    }
    .highlight__of {
      margin-left: 4px;
      font-size: var(--fs-md);
      font-weight: 500;
      color: var(--c-text-2);
    }
    .agent {
      display: flex;
      flex-direction: column;
      gap: var(--s-2);
      padding-top: 0;
    }
    .agent__text {
      white-space: pre-line;
      background: var(--c-success-bg);
      border-color: #bfe3d3;
    }
    .card-footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: var(--s-3);
      padding: var(--s-3) var(--s-4);
      border-top: 1px solid var(--c-border);
      background: var(--c-surface-muted);
      border-radius: 0 0 var(--r-lg) var(--r-lg);
    }
  `,
})
export class InspectorSummary {
  readonly result = input.required<FirewallResult>();

  protected readonly categories = computed(() => {
    const counts = new Map<string, number>();
    for (const e of this.result().entities) {
      counts.set(e.entity_type, (counts.get(e.entity_type) ?? 0) + 1);
    }
    return [...counts].map(([type, count]) => ({ type, count }));
  });

  protected readonly routeLabel = computed(() => {
    const route = this.result().routing?.route;
    return route === 'CLOUD' ? 'Routed to cloud stand-in' : route === 'LOCAL' ? 'Kept local' : 'Not processed';
  });

  protected readonly steps = computed(() => {
    const steps = this.result().steps;
    const skipped = steps.filter((s) => s.status === 'SKIPPED').length;
    const completed = steps.filter((s) => s.status === 'COMPLETED').length;
    return { total: steps.length - skipped, completed, skipped, issues: steps.length - skipped - completed };
  });
}
