import { TestBed } from '@angular/core/testing';

import { testProviders } from '../../testing/test-providers';
import { StatusBadge } from './components/status-badge';
import { splitPlaceholders } from '../features/inspector/highlighted-text';
import { formatDuration, humanize } from './pipes/format.pipes';

describe('format helpers', () => {
  it('humanizes backend enums', () => {
    expect(humanize('COMPLETED_WITH_WARNINGS')).toBe('Completed with warnings');
    expect(humanize(null)).toBe('');
  });

  it('formats measured durations', () => {
    expect(formatDuration(null)).toBe('-');
    expect(formatDuration(0.4)).toBe('<1 ms');
    expect(formatDuration(245.6)).toBe('246 ms');
    expect(formatDuration(2714)).toBe('2.71 s');
  });

  it('splits placeholder tokens for highlighting', () => {
    const parts = splitPlaceholders('My name is [PERSON], ID [PATIENT_ID].');
    expect(parts.filter((p) => p.kind === 'placeholder').map((p) => p.text)).toEqual(['[PERSON]', '[PATIENT_ID]']);
    expect(parts.map((p) => p.text).join('')).toBe('My name is [PERSON], ID [PATIENT_ID].');
  });
});

describe('StatusBadge', () => {
  beforeEach(() => TestBed.configureTestingModule({ providers: testProviders() }));

  async function render(value: string) {
    const fixture = TestBed.createComponent(StatusBadge);
    fixture.componentRef.setInput('value', value);
    await fixture.whenStable();
    return fixture.nativeElement.querySelector('.badge') as HTMLElement;
  }

  it('uses text and a variant for each decision', async () => {
    const blocked = await render('BLOCKED');
    expect(blocked.textContent?.trim()).toBe('Blocked');
    expect(blocked.className).toContain('badge-error');

    const local = await render('LOCAL_ONLY');
    expect(local.textContent?.trim()).toBe('Local only');
    expect(local.className).toContain('badge-local');
  });

  it('falls back to a neutral badge for unknown values', async () => {
    const unknown = await render('SOMETHING_NEW');
    expect(unknown.className).toContain('badge-neutral');
    expect(unknown.textContent?.trim()).toBe('Something new');
  });
});
