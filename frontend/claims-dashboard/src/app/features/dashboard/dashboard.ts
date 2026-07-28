import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';

@Component({
  selector: 'app-dashboard',
  imports: [],
  templateUrl: './dashboard.html',
})
export class Dashboard {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly user = this.auth.user;
  readonly failed = signal(false);

  constructor() {
    this.auth.loadCurrentUser().subscribe({
      error: () => this.failed.set(true),
    });
  }

  signOut(): void {
    this.auth.logout();
    void this.router.navigate(['/login']);
  }
}
