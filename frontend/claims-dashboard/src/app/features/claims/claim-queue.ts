import { DecimalPipe, SlicePipe } from '@angular/common';
import { Component, computed, effect, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

import { ClaimStreamService } from '../../core/claim-stream.service';
import {
  ALL_STATUSES,
  Claim,
  ClaimStatus,
  ClaimsService,
  STATUS_LABELS,
} from '../../core/claims.service';

const PAGE_SIZE = 15;

@Component({
  selector: 'app-claim-queue',
  imports: [DecimalPipe, SlicePipe],
  templateUrl: './claim-queue.html',
  styleUrl: './claim-queue.scss',
})
export class ClaimQueue {
  private readonly claims = inject(ClaimsService);
  private readonly stream = inject(ClaimStreamService);
  private readonly router = inject(Router);

  readonly statuses = ALL_STATUSES;
  readonly labels = STATUS_LABELS;

  readonly items = signal<Claim[]>([]);
  readonly total = signal(0);
  readonly offset = signal(0);
  readonly statusFilter = signal<ClaimStatus | null>(null);
  readonly mineOnly = signal(false);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);

  readonly pageSize = PAGE_SIZE;
  readonly hasPrevious = computed(() => this.offset() > 0);
  readonly hasNext = computed(() => this.offset() + PAGE_SIZE < this.total());
  readonly showing = computed(() => {
    const start = this.total() === 0 ? 0 : this.offset() + 1;
    return { start, end: Math.min(this.offset() + PAGE_SIZE, this.total()) };
  });

  constructor() {
    // Refetch whenever a filter changes. Reading the signals inside the effect
    // is what registers the dependency; no manual wiring per control.
    effect(() => {
      this.statusFilter();
      this.mineOnly();
      this.offset();
      this.load();
    });

    // A claim event means this page is stale. Refetching is deliberate rather
    // than patching the row in place: the event carries a status change, but
    // the row may also have moved in or out of the current filter and page.
    // Refetching keeps one source of truth and avoids a divergent local copy.
    effect(() => {
      const event = this.stream.lastEvent();
      if (event && event.type !== 'connected') {
        this.load();
      }
    });
  }

  setStatus(value: string): void {
    this.offset.set(0);
    this.statusFilter.set(value === '' ? null : (value as ClaimStatus));
  }

  toggleMine(): void {
    this.offset.set(0);
    this.mineOnly.update((value) => !value);
  }

  previous(): void {
    this.offset.update((value) => Math.max(0, value - PAGE_SIZE));
  }

  next(): void {
    this.offset.update((value) => value + PAGE_SIZE);
  }

  open(claim: Claim): void {
    void this.router.navigate(['/claims', claim.id]);
  }

  private load(): void {
    this.loading.set(true);
    this.claims
      .list({
        status: this.statusFilter(),
        mine: this.mineOnly(),
        limit: PAGE_SIZE,
        offset: this.offset(),
      })
      .subscribe({
        next: (page) => {
          this.items.set(page.items);
          this.total.set(page.total);
          this.loading.set(false);
          this.error.set(null);
        },
        error: () => {
          this.loading.set(false);
          this.error.set('Could not load claims.');
        },
      });
  }
}
