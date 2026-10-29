import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { EntityResult } from '../../core/models/api.models';
import { humanize } from '../../shared/pipes/format.pipes';

interface Segment {
  text: string;
  kind: 'plain' | 'entity' | 'placeholder';
  label?: string;
}

const PLACEHOLDER = /\[[A-Z][A-Z0-9_]{1,39}\]/g;

/**
 * Renders text with detected entity spans (original) or placeholder tokens (redacted)
 * highlighted. Uses text interpolation only, never innerHTML.
 */
@Component({
  selector: 'app-highlighted-text',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<div class="text-block">@for (s of segments(); track $index) {@switch (s.kind) {@case ('entity') {<mark class="entity-mark" [attr.title]="s.label">{{ s.text }}</mark>}@case ('placeholder') {<span class="placeholder-token">{{ s.text }}</span>}@default {<ng-container>{{ s.text }}</ng-container>}}}</div>`,
  styles: `
    mark {
      color: inherit;
    }
  `,
})
export class HighlightedText {
  readonly text = input.required<string>();
  readonly entities = input<EntityResult[]>([]);
  readonly mode = input<'entities' | 'placeholders'>('entities');

  protected readonly segments = computed<Segment[]>(() => {
    const text = this.text();
    if (this.mode() === 'placeholders') {
      return splitPlaceholders(text);
    }
    const spans = [...this.entities()]
      .filter((e) => e.start >= 0 && e.end <= text.length && e.start < e.end)
      .sort((a, b) => a.start - b.start);
    const out: Segment[] = [];
    let cursor = 0;
    for (const e of spans) {
      if (e.start < cursor) {
        continue;
      }
      if (e.start > cursor) {
        out.push({ text: text.slice(cursor, e.start), kind: 'plain' });
      }
      out.push({ text: text.slice(e.start, e.end), kind: 'entity', label: `${humanize(e.entity_type)} (${humanize(e.action)})` });
      cursor = e.end;
    }
    if (cursor < text.length) {
      out.push({ text: text.slice(cursor), kind: 'plain' });
    }
    return out;
  });
}

export function splitPlaceholders(text: string): Segment[] {
  const out: Segment[] = [];
  let cursor = 0;
  for (const match of text.matchAll(PLACEHOLDER)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      out.push({ text: text.slice(cursor, index), kind: 'plain' });
    }
    out.push({ text: match[0], kind: 'placeholder' });
    cursor = index + match[0].length;
  }
  if (cursor < text.length) {
    out.push({ text: text.slice(cursor), kind: 'plain' });
  }
  return out;
}
