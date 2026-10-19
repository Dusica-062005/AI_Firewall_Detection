import { Injectable, inject, signal } from '@angular/core';

import { ApiError, Controls, HealthResponse } from '../models/api.models';
import { FirewallApiService } from './firewall-api.service';

/** Shared backend health and operator controls used by the top bar. Refreshed on demand and every 30 seconds. */
@Injectable({ providedIn: 'root' })
export class SystemStatusService {
  private readonly api = inject(FirewallApiService);
  private timer: ReturnType<typeof setInterval> | null = null;

  readonly health = signal<HealthResponse | null>(null);
  readonly error = signal<ApiError | null>(null);
  readonly loading = signal(false);
  /** Kill switch and dial; pages that change them set this so the top bar updates at once. */
  readonly controls = signal<Controls | null>(null);

  start(): void {
    this.refresh();
    this.timer ??= setInterval(() => this.refresh(), 30000);
  }

  refresh(): void {
    this.loading.set(true);
    this.api.health().subscribe({
      next: (health) => {
        this.health.set(health);
        this.error.set(null);
        this.loading.set(false);
      },
      error: (error: ApiError) => {
        this.health.set(null);
        this.error.set(error);
        this.loading.set(false);
      },
    });
    this.api.controls().subscribe({
      next: (controls) => this.controls.set(controls),
      error: () => this.controls.set(null),
    });
  }
}
