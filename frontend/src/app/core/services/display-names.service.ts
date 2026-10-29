import { Injectable, inject, signal } from '@angular/core';

import { humanize } from '../../shared/pipes/format.pipes';
import { FirewallApiService } from './firewall-api.service';

/**
 * Readable names for the policy and profile IDs that audit records and results carry.
 * Falls back to a humanized ID until the lists load, or for IDs that no longer exist.
 */
@Injectable({ providedIn: 'root' })
export class DisplayNamesService {
  private readonly api = inject(FirewallApiService);
  private readonly policies = signal<Record<string, string>>({});
  private readonly profiles = signal<Record<string, string>>({});

  /** Fetches both lists; pages call this on load so renamed policies show their current name. */
  load(): void {
    this.api.policies().subscribe({
      next: (res) => this.policies.set(Object.fromEntries(res.items.map((p) => [p.policy_id, p.name]))),
      error: () => undefined,
    });
    this.api.profiles().subscribe({
      next: (res) => this.profiles.set(Object.fromEntries(res.items.map((p) => [p.id, p.name]))),
      error: () => undefined,
    });
  }

  policy(id: string | null | undefined): string {
    return id ? (this.policies()[id] ?? humanize(id)) : '-';
  }

  profile(id: string | null | undefined): string {
    return id ? (this.profiles()[id] ?? humanize(id)) : '-';
  }
}
