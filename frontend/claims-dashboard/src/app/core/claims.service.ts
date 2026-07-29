import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE_URL } from './config';

export type ClaimStatus =
  | 'submitted'
  | 'triaged'
  | 'under_review'
  | 'pending_approval'
  | 'approved'
  | 'settled'
  | 'denied'
  | 'withdrawn';

export type RiskBand = 'low' | 'medium' | 'high';

export interface Claim {
  id: string;
  claim_number: string;
  policy_id: string;
  assigned_adjuster_id: string | null;
  loss_date: string;
  reported_date: string;
  loss_type: string;
  description: string;
  claimed_amount: string;
  status: ClaimStatus;
  settled_amount: string | null;
  risk_band: RiskBand | null;
  created_at: string;
  updated_at: string;
}

export interface ClaimDetail extends Claim {
  available_transitions: ClaimStatus[];
}

export interface ClaimPage {
  items: Claim[];
  total: number;
  limit: number;
  offset: number;
}

export interface HistoryEntry {
  from_status: string | null;
  to_status: string;
  actor_id: string | null;
  actor_type: string;
  reason: string | null;
  created_at: string;
}

export interface ClaimDocument {
  id: string;
  claim_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  doc_type: string;
  processing_status: string;
  created_at: string;
}

export interface ListOptions {
  status?: ClaimStatus | null;
  mine?: boolean;
  limit?: number;
  offset?: number;
}

@Injectable({ providedIn: 'root' })
export class ClaimsService {
  private readonly http = inject(HttpClient);

  list(options: ListOptions = {}): Observable<ClaimPage> {
    let params = new HttpParams()
      .set('limit', options.limit ?? 25)
      .set('offset', options.offset ?? 0);

    if (options.status) {
      params = params.set('status', options.status);
    }
    if (options.mine) {
      params = params.set('mine', true);
    }

    return this.http.get<ClaimPage>(`${API_BASE_URL}/claims`, { params });
  }

  get(claimId: string): Observable<ClaimDetail> {
    return this.http.get<ClaimDetail>(`${API_BASE_URL}/claims/${claimId}`);
  }

  history(claimId: string): Observable<HistoryEntry[]> {
    return this.http.get<HistoryEntry[]>(`${API_BASE_URL}/claims/${claimId}/history`);
  }

  documents(claimId: string): Observable<ClaimDocument[]> {
    return this.http.get<ClaimDocument[]>(`${API_BASE_URL}/claims/${claimId}/documents`);
  }

  assessment(claimId: string): Observable<Assessment> {
    return this.http.get<Assessment>(`${API_BASE_URL}/claims/${claimId}/assessment`);
  }

  source(sourceType: string, sourceId: string): Observable<SourceDetail> {
    return this.http.get<SourceDetail>(`${API_BASE_URL}/sources/${sourceType}/${sourceId}`);
  }

  transition(
    claimId: string,
    toStatus: ClaimStatus,
    settlementAmount?: string,
    reason?: string,
  ): Observable<Claim> {
    return this.http.post<Claim>(`${API_BASE_URL}/claims/${claimId}/transitions`, {
      to_status: toStatus,
      settlement_amount: settlementAmount ?? null,
      reason: reason ?? null,
    });
  }
}

export const STATUS_LABELS: Record<ClaimStatus, string> = {
  submitted: 'Submitted',
  triaged: 'Triaged',
  under_review: 'Under review',
  pending_approval: 'Pending approval',
  approved: 'Approved',
  settled: 'Settled',
  denied: 'Denied',
  withdrawn: 'Withdrawn',
};

export const ALL_STATUSES: ClaimStatus[] = [
  'submitted',
  'triaged',
  'under_review',
  'pending_approval',
  'approved',
  'settled',
  'denied',
  'withdrawn',
];


export interface Citation {
  id: string;
  source_type: 'policy_chunk' | 'precedent';
  source_id: string;
  source_ref: string;
  relevance: string | null;
  quoted_span: string | null;
  supports: 'coverage' | 'risk' | 'amount';
}

export interface Assessment {
  id: string;
  claim_id: string;
  coverage_verdict: 'covered' | 'partially_covered' | 'not_covered' | 'indeterminate';
  coverage_rationale: string;
  risk_score: string;
  risk_band: RiskBand;
  risk_rationale: string;
  recommended_amount: string | null;
  model_version: string;
  prompt_version: number;
  latency_ms: number;
  created_at: string;
  citations: Citation[];
}

export interface SourceDetail {
  source_type: string;
  source_id: string;
  source_ref: string;
  body: string;
  metadata: Record<string, unknown>;
}

export const VERDICT_LABELS: Record<Assessment['coverage_verdict'], string> = {
  covered: 'Covered',
  partially_covered: 'Partially covered',
  not_covered: 'Not covered',
  indeterminate: 'Indeterminate',
};
