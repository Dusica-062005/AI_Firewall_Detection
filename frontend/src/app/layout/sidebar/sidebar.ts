import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { LucideDynamicIcon } from '@lucide/angular';

interface NavItem {
  path: string;
  label: string;
  icon: string;
}

@Component({
  selector: 'app-sidebar',
  imports: [RouterLink, RouterLinkActive, LucideDynamicIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './sidebar.html',
  styleUrl: './sidebar.scss',
  host: { '[class.is-collapsed]': 'collapsed()' },
})
export class Sidebar {
  readonly collapsed = input(false);
  readonly toggle = output<void>();

  protected readonly items: NavItem[] = [
    { path: '/overview', label: 'Overview', icon: 'layout-dashboard' },
    { path: '/inspector', label: 'Transcript Inspector', icon: 'scan-search' },
    { path: '/policies', label: 'Policy Management', icon: 'list-checks' },
    { path: '/trust', label: 'Trust & Controls', icon: 'fingerprint' },
    { path: '/audit', label: 'Audit Trail', icon: 'file-text' },
    { path: '/compliance', label: 'Compliance Center', icon: 'clipboard-check' },
    { path: '/settings', label: 'Settings', icon: 'settings' },
  ];
}
