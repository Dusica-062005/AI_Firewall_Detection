import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { Router } from '@angular/router';

import { FrameworkId } from '../../core/models/api.models';
import { AiSystems } from './ai-systems';
import { ComplianceOverviewTab } from './compliance-overview';
import { DataRequests } from './data-requests';
import { EvidencePackTab } from './evidence-pack';
import { Incidents } from './incidents';

export type ComplianceTab = 'overview' | 'evidence' | 'incidents' | 'requests' | 'systems';

const TABS: { id: ComplianceTab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'evidence', label: 'Evidence pack' },
  { id: 'incidents', label: 'Incidents' },
  { id: 'requests', label: 'Data requests' },
  { id: 'systems', label: 'AI systems' },
];

@Component({
  selector: 'app-compliance',
  imports: [ComplianceOverviewTab, EvidencePackTab, Incidents, DataRequests, AiSystems],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './compliance.html',
  styleUrl: './compliance.scss',
})
export class Compliance {
  private readonly router = inject(Router);

  /** Bound from the ?tab= query parameter so a tab can be linked to directly. */
  readonly tab = input<string | undefined>();

  protected readonly tabs = TABS;
  protected readonly framework = signal<FrameworkId>('GDPR');
  protected readonly current = computed<ComplianceTab>(() => TABS.find((t) => t.id === this.tab())?.id ?? 'overview');

  protected select(tab: ComplianceTab): void {
    this.router.navigate([], { queryParams: { tab }, queryParamsHandling: 'merge' });
  }

  protected openEvidence(framework: FrameworkId): void {
    this.framework.set(framework);
    this.select('evidence');
  }

  protected onTabKey(event: KeyboardEvent): void {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (!step) {
      return;
    }
    const index = TABS.findIndex((t) => t.id === this.current());
    const next = TABS[(index + step + TABS.length) % TABS.length];
    this.select(next.id);
    queueMicrotask(() => document.getElementById('ctab-' + next.id)?.focus());
    event.preventDefault();
  }
}
