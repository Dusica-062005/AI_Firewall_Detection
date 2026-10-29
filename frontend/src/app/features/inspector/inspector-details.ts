import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { LucideDynamicIcon } from '@lucide/angular';

import { InspectorResult } from './inspector-result';
import { InspectorStateService } from './inspector-state.service';

/** Full processing details for the last Inspector result (kept in memory, never in browser storage). */
@Component({
  selector: 'app-inspector-details',
  imports: [RouterLink, LucideDynamicIcon, InspectorResult],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <header class="page-header">
        <div class="page-header__text">
          <a class="btn btn-ghost btn-sm back-link" routerLink="/inspector">
            <svg class="icon" lucideIcon="chevron-left" aria-hidden="true"></svg>
            Back to Inspector
          </a>
          <h1>Processing details</h1>
          <p>Everything the firewall did with this request: what each model saw, which values were protected, how policy decided and what was audited.</p>
        </div>
      </header>

      @if (result(); as r) {
        <app-inspector-result [result]="r" [original]="submitted()" />
      } @else {
        <div class="card">
          <div class="empty-state">
            <svg class="icon" lucideIcon="scan-search" aria-hidden="true"></svg>
            <span class="empty-state__title">No result to show</span>
            <span>Process a synthetic transcript in the Inspector first. Results are kept in memory only, so they clear when the page is reloaded.</span>
            <a class="btn btn-primary" routerLink="/inspector">Go to Inspector</a>
          </div>
        </div>
      }
    </div>
  `,
  styles: `
    .back-link {
      align-self: flex-start;
      margin: 0 0 var(--s-2) calc(var(--s-2) * -1);
    }
  `,
})
export class InspectorDetails {
  private readonly state = inject(InspectorStateService);
  protected readonly result = this.state.result;
  protected readonly submitted = this.state.submittedTranscript;
}
