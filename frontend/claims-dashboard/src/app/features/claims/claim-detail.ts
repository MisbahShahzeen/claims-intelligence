import { DecimalPipe, SlicePipe } from '@angular/common';
import { Component, computed, inject, input, signal } from '@angular/core';
import { Router } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';
import {
  Assessment,
  Citation,
  ClaimDetail as ClaimDetailModel,
  ClaimDocument,
  ClaimStatus,
  ClaimsService,
  HistoryEntry,
  STATUS_LABELS,
  SourceDetail,
  VERDICT_LABELS,
} from '../../core/claims.service';

@Component({
  selector: 'app-claim-detail',
  imports: [DecimalPipe, SlicePipe],
  templateUrl: './claim-detail.html',
  styleUrl: './claim-detail.scss',
})
export class ClaimDetail {
  readonly claimId = input.required<string>();

  private readonly claims = inject(ClaimsService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly labels = STATUS_LABELS;
  readonly verdictLabels = VERDICT_LABELS;

  readonly claim = signal<ClaimDetailModel | null>(null);
  readonly assessment = signal<Assessment | null>(null);
  readonly documents = signal<ClaimDocument[]>([]);
  readonly history = signal<HistoryEntry[]>([]);
  readonly openSource = signal<SourceDetail | null>(null);

  readonly loading = signal(true);
  readonly notAssessed = signal(false);
  readonly actionError = signal<string | null>(null);
  readonly working = signal(false);

  readonly settlementAmount = signal('');
  readonly reason = signal('');

  readonly authorityLimit = computed(() => {
    const value = this.auth.user()?.authority_limit;
    return value ? Number(value) : 0;
  });

  // Grouped for display. A clause can legitimately support both coverage and
  // risk, and appears once per grouping - the repetition carries meaning.
  readonly coverageCitations = computed(() => this.citationsFor('coverage'));
  readonly riskCitations = computed(() => this.citationsFor('risk'));
  readonly amountCitations = computed(() => this.citationsFor('amount'));

  constructor() {
    queueMicrotask(() => this.load());
  }

  needsAmount(status: ClaimStatus): boolean {
    return status === 'approved' || status === 'pending_approval';
  }

  act(target: ClaimStatus): void {
    if (this.working()) {
      return;
    }
    const amount = this.settlementAmount().trim();
    if (this.needsAmount(target) && !amount) {
      this.actionError.set('A settlement amount is required for this action.');
      return;
    }

    this.working.set(true);
    this.actionError.set(null);

    this.claims
      .transition(this.claimId(), target, amount || undefined, this.reason().trim() || undefined)
      .subscribe({
        next: () => {
          this.working.set(false);
          this.settlementAmount.set('');
          this.reason.set('');
          this.load();
        },
        error: (error: { status?: number; error?: { detail?: string } }) => {
          this.working.set(false);
          this.actionError.set(error.error?.detail ?? 'That action was rejected.');
        },
      });
  }

  showSource(citation: Citation): void {
    this.claims.source(citation.source_type, citation.source_id).subscribe({
      next: (detail) => this.openSource.set(detail),
      error: () => this.openSource.set(null),
    });
  }

  closeSource(): void {
    this.openSource.set(null);
  }

  back(): void {
    void this.router.navigate(['/dashboard']);
  }

  /** Split a rationale into text and inline citation references.
   *
   * The model writes markers like [clause:uuid] so its citations can be
   * verified against what it was given. Those markers are machinery, not prose:
   * rendering them raw leaks the prompt format to the adjuster. Turning them
   * into links keeps the traceability and loses the noise.
   */
  segments(rationale: string): { text: string; citation: Citation | null }[] {
    const citations = this.assessment()?.citations ?? [];
    const parts: { text: string; citation: Citation | null }[] = [];
    const pattern = /\[(clause|precedent):([0-9a-f-]{36})\]/g;

    let cursor = 0;
    for (const match of rationale.matchAll(pattern)) {
      const index = match.index ?? 0;
      if (index > cursor) {
        parts.push({ text: rationale.slice(cursor, index), citation: null });
      }
      const found = citations.find((c) => c.source_id === match[2]);
      if (found) {
        parts.push({ text: found.source_ref, citation: found });
      }
      cursor = index + match[0].length;
    }
    if (cursor < rationale.length) {
      parts.push({ text: rationale.slice(cursor), citation: null });
    }
    return parts;
  }

  private citationsFor(kind: Citation['supports']): Citation[] {
    return (this.assessment()?.citations ?? []).filter((c) => c.supports === kind);
  }

  private load(): void {
    const id = this.claimId();
    this.loading.set(true);

    this.claims.get(id).subscribe({
      next: (claim) => {
        this.claim.set(claim);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });

    // A missing assessment is a normal state, not an error. The API returns
    // 404 and the view renders "not assessed yet" rather than failing.
    this.claims.assessment(id).subscribe({
      next: (assessment) => {
        this.assessment.set(assessment);
        this.notAssessed.set(false);
      },
      error: () => {
        this.assessment.set(null);
        this.notAssessed.set(true);
      },
    });

    this.claims.documents(id).subscribe({ next: (docs) => this.documents.set(docs) });
    this.claims.history(id).subscribe({ next: (entries) => this.history.set(entries) });
  }
}
