import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

import { API_BASE_URL } from '../config';

export type UserRole = 'adjuster' | 'senior_adjuster' | 'admin';

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  authority_limit: string;
  is_active: boolean;
}

interface TokenResponse {
  access_token: string;
  token_type: string;
}

const TOKEN_KEY = 'claims.access_token';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);

  private readonly _token = signal<string | null>(localStorage.getItem(TOKEN_KEY));
  private readonly _user = signal<User | null>(null);

  readonly token = this._token.asReadonly();
  readonly user = this._user.asReadonly();
  readonly isAuthenticated = computed(() => this._token() !== null);
  readonly isSenior = computed(() => {
    const role = this._user()?.role;
    return role === 'senior_adjuster' || role === 'admin';
  });

  login(email: string, password: string): Observable<TokenResponse> {
    return this.http
      .post<TokenResponse>(`${API_BASE_URL}/auth/login`, { email, password })
      .pipe(tap((response) => this.setToken(response.access_token)));
  }

  loadCurrentUser(): Observable<User> {
    return this.http
      .get<User>(`${API_BASE_URL}/auth/me`)
      .pipe(tap((user) => this._user.set(user)));
  }

  logout(): void {
    localStorage.removeItem(TOKEN_KEY);
    this._token.set(null);
    this._user.set(null);
  }

  private setToken(token: string): void {
    localStorage.setItem(TOKEN_KEY, token);
    this._token.set(token);
  }
}
