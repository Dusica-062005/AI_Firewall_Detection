import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { SystemStatusService } from '../../core/services/system-status.service';
import { ToastContainer } from '../../shared/components/toast-container';
import { Sidebar } from '../sidebar/sidebar';
import { Topbar } from '../topbar/topbar';

const COLLAPSE_KEY = 'maf.sidebarCollapsed';

@Component({
  selector: 'app-main-layout',
  imports: [RouterOutlet, Sidebar, Topbar, ToastContainer],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a class="skip-link" href="#main-content">Skip to content</a>
    <app-sidebar [collapsed]="collapsed()" (toggle)="toggle()" />
    <div class="shell__main">
      <app-topbar />
      <main id="main-content" class="shell__content" tabindex="-1">
        <router-outlet />
      </main>
    </div>
    <app-toast-container />
  `,
  styles: `
    :host {
      display: flex;
      height: 100vh;
      overflow: hidden;
    }
    .shell__main {
      flex: 1;
      display: flex;
      flex-direction: column;
      min-width: 0;
    }
    .shell__content {
      flex: 1;
      overflow-y: auto;
      overflow-x: hidden;
      outline: none;
    }
    .skip-link {
      position: absolute;
      left: 8px;
      top: -40px;
      z-index: 100;
      padding: 8px 12px;
      background: var(--c-surface);
      border-radius: var(--r-md);
    }
    .skip-link:focus {
      top: 8px;
    }
  `,
})
export class MainLayout implements OnInit {
  private readonly status = inject(SystemStatusService);
  protected readonly collapsed = signal(this.readCollapsed());

  ngOnInit(): void {
    this.status.start();
  }

  protected toggle(): void {
    this.collapsed.update((v) => !v);
    try {
      localStorage.setItem(COLLAPSE_KEY, String(this.collapsed()));
    } catch {
      // Preference only.
    }
  }

  private readCollapsed(): boolean {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === 'true' || window.innerWidth < 900;
    } catch {
      return false;
    }
  }
}
