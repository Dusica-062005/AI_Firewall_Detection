import { ChangeDetectionStrategy, Component, OnInit, computed, inject, output, signal } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';

import { ApiError, ComplianceOverview, ControlResult, FrameworkId } from '../../core/models/api.models';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { ErrorAlert } from '../../shared/components/error-alert';
import { StatusBadge } from '../../shared/components/status-badge';

interface Gap {
  control: ControlResult;
  frameworks: string[];
}

export function scoreTone(score: number): 'success' | 'warning' | 'error' {
  return score >= 80 ? 'success' : score >= 50 ? 'warning' : 'error';
}

@Component({
  selector: 'app-compliance-overview',
  imports: [LucideDynamicIcon, StatusBadge, ErrorAlert],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './compliance-overview.html',
  styleUrl: './compliance.scss',
})
export class ComplianceOverviewTab implements OnInit {
  private readonly api = inject(FirewallApiService);

  readonly evidence = output<FrameworkId>();
  readonly openTab = output<'incidents' | 'requests' | 'systems'>();

  protected readonly data = signal<ComplianceOverview | null>(null);
  protected readonly loading = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly tone = scoreTone;

  /** Controls that are not passing, merged across frameworks, worst first. */
  protected readonly gaps = computed<Gap[]>(() => {
    const merged = new Map<string, Gap>();
    for (const framework of this.data()?.frameworks ?? []) {
      for (const control of framework.controls.filter((c) => c.status !== 'PASS')) {
        const gap = merged.get(control.control_id) ?? { control, frameworks: [] };
        gap.frameworks.push(framework.name);
        merged.set(control.control_id, gap);
      }
    }
    const rank = { FAIL: 0, PARTIAL: 1, PASS: 2 };
    return [...merged.values()].sort((a, b) => rank[a.control.status] - rank[b.control.status]);
  });

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.complianceOverview().subscribe({
      next: (res) => {
        this.data.set(res);
        this.loading.set(false);
      },
      error: (err: ApiError) => {
        this.error.set(err);
        this.loading.set(false);
      },
    });
  }
}
