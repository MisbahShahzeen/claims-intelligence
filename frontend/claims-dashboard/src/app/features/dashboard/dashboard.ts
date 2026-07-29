import { SlicePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';
import { ClaimStreamService } from '../../core/claim-stream.service';

@Component({
  selector: 'app-dashboard',
  imports: [SlicePipe],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.scss',
})
export class Dashboard {
  private readonly auth = inject(AuthService);
  private readonly stream = inject(ClaimStreamService);
  private readonly router = inject(Router);

  readonly user = this.auth.user;
  readonly failed = signal(false);

  readonly connectionState = this.stream.state;
  readonly isLive = this.stream.isLive;
  readonly events = this.stream.events;

  constructor() {
    this.auth.loadCurrentUser().subscribe({
      error: () => this.failed.set(true),
    });
  }

  signOut(): void {
    this.auth.logout();
    void this.router.navigate(['/login']);
  }

  describe(event: { type: string; from_status?: string; to_status?: string; status?: string; risk_band?: string }): string {
    if (event.type === 'claim.status_changed') {
      return `${event.from_status} → ${event.to_status}`;
    }
    if (event.type === 'claim.assessed') {
      return `assessed, risk ${event.risk_band}`;
    }
    return event.status ?? event.type;
  }
}
