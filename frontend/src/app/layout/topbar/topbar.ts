import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink } from '@angular/router';
import { LucideDynamicIcon } from '@lucide/angular';
import { filter, map, startWith } from 'rxjs';

import { SystemStatusService } from '../../core/services/system-status.service';

@Component({
  selector: 'app-topbar',
  imports: [LucideDynamicIcon, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './topbar.html',
  styleUrl: './topbar.scss',
})
export class Topbar {
  private readonly router = inject(Router);
  protected readonly status = inject(SystemStatusService);

  protected readonly pageTitle = toSignal(
    this.router.events.pipe(
      filter((e) => e instanceof NavigationEnd),
      startWith(null),
      map(() => {
        let snapshot = this.router.routerState.snapshot.root;
        while (snapshot.firstChild) {
          snapshot = snapshot.firstChild;
        }
        return (snapshot.data?.['title'] as string | undefined) ?? '';
      }),
    ),
    { initialValue: '' },
  );

  protected readonly connection = computed(() => {
    const health = this.status.health();
    if (this.status.error()) {
      return { tone: 'error', label: 'Backend unreachable', icon: 'circle-x' };
    }
    if (!health) {
      return { tone: 'neutral', label: 'Checking backend', icon: 'circle-dashed' };
    }
    const core = ['database', 'detection', 'policies'].every((k) => health.components[k]?.status === 'READY');
    if (!core) {
      return { tone: 'error', label: 'Enforcement degraded', icon: 'shield-alert' };
    }
    return health.status === 'ok'
      ? { tone: 'success', label: 'Firewall active', icon: 'shield-check' }
      : { tone: 'warning', label: 'Firewall active, integrations degraded', icon: 'triangle-alert' };
  });
}
