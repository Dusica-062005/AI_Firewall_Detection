import { Routes } from '@angular/router';

import { MainLayout } from './layout/main-layout/main-layout';

export const routes: Routes = [
  {
    path: '',
    component: MainLayout,
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'overview' },
      {
        path: 'overview',
        title: 'Overview - AI Data Firewall',
        data: { title: 'Overview' },
        loadComponent: () => import('./features/overview/overview').then((m) => m.Overview),
      },
      {
        path: 'inspector',
        title: 'Transcript Inspector - AI Data Firewall',
        data: { title: 'Transcript Inspector' },
        loadComponent: () => import('./features/inspector/inspector').then((m) => m.Inspector),
      },
      {
        path: 'policies',
        title: 'Policy Management - AI Data Firewall',
        data: { title: 'Policy Management' },
        loadComponent: () => import('./features/policies/policies').then((m) => m.Policies),
      },
      {
        path: 'audit',
        title: 'Audit Trail - AI Data Firewall',
        data: { title: 'Audit Trail' },
        loadComponent: () => import('./features/audit/audit').then((m) => m.Audit),
      },
      {
        path: 'trust',
        title: 'Trust & Controls - AI Data Firewall',
        data: { title: 'Trust & Controls' },
        loadComponent: () => import('./features/trust/trust').then((m) => m.Trust),
      },
      {
        path: 'compliance',
        title: 'Compliance Center - AI Data Firewall',
        data: { title: 'Compliance & Incident Center' },
        loadComponent: () => import('./features/compliance/compliance').then((m) => m.Compliance),
      },
      {
        path: 'settings',
        title: 'Settings - AI Data Firewall',
        data: { title: 'Settings' },
        loadComponent: () => import('./features/settings/settings').then((m) => m.Settings),
      },
      { path: '**', redirectTo: 'overview' },
    ],
  },
];
