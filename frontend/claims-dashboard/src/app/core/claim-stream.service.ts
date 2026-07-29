import { Injectable, computed, effect, inject, signal } from '@angular/core';

import { AuthService } from './auth/auth.service';

export interface ClaimEvent {
  type: string;
  claim_id?: string;
  claim_number?: string;
  occurred_at?: string;
  status?: string;
  from_status?: string;
  to_status?: string;
  risk_band?: string;
  coverage_verdict?: string;
  risk_score?: number;
}

type ConnectionState = 'idle' | 'connecting' | 'open' | 'reconnecting';

const WS_URL = 'ws://localhost:8000/ws/claims';
const MAX_BACKOFF_MS = 30_000;
const HEARTBEAT_MS = 25_000;

@Injectable({ providedIn: 'root' })
export class ClaimStreamService {
  private readonly auth = inject(AuthService);

  private socket: WebSocket | null = null;
  private reconnectTimer: number | null = null;
  private heartbeatTimer: number | null = null;
  private attempt = 0;
  private deliberateClose = false;

  private readonly _state = signal<ConnectionState>('idle');
  private readonly _lastEvent = signal<ClaimEvent | null>(null);
  private readonly _events = signal<ClaimEvent[]>([]);

  readonly state = this._state.asReadonly();
  readonly lastEvent = this._lastEvent.asReadonly();
  readonly events = this._events.asReadonly();
  readonly isLive = computed(() => this._state() === 'open');

  constructor() {
    // Follow the auth state: connect on login, disconnect on logout. Without
    // this the socket would outlive the session and keep pushing claim data
    // to a signed-out browser.
    effect(() => {
      if (this.auth.isAuthenticated()) {
        this.connect();
      } else {
        this.disconnect();
      }
    });
  }

  connect(): void {
    if (this.socket || !this.auth.token()) {
      return;
    }
    this.deliberateClose = false;
    this._state.set(this.attempt === 0 ? 'connecting' : 'reconnecting');

    const socket = new WebSocket(WS_URL);
    this.socket = socket;

    socket.onopen = () => {
      // Auth is the first message, not a query parameter: tokens in URLs end
      // up in proxy logs and browser history.
      socket.send(JSON.stringify({ token: this.auth.token() }));
      this.attempt = 0;
      this._state.set('open');
      this.startHeartbeat();
    };

    socket.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as ClaimEvent;
        this._lastEvent.set(event);
        this._events.update((all) => [event, ...all].slice(0, 50));
      } catch {
        // Ignore anything that isn't JSON rather than tearing down the socket.
      }
    };

    socket.onclose = (closeEvent) => {
      this.stopHeartbeat();
      this.socket = null;

      // 4401 means the token was rejected. Reconnecting with the same token
      // would loop forever, so treat it as a terminal auth failure instead.
      if (this.deliberateClose || closeEvent.code === 4401) {
        this._state.set('idle');
        return;
      }
      this.scheduleReconnect();
    };

    socket.onerror = () => socket.close();
  }

  disconnect(): void {
    this.deliberateClose = true;
    this.clearReconnect();
    this.stopHeartbeat();
    this.socket?.close();
    this.socket = null;
    this.attempt = 0;
    this._state.set('idle');
  }

  private scheduleReconnect(): void {
    this.clearReconnect();
    this.attempt += 1;
    this._state.set('reconnecting');

    // Exponential backoff with jitter. Without the random component, every
    // client disconnected by a server restart reconnects in lockstep and
    // hits the server as one synchronised wave.
    const base = Math.min(2 ** this.attempt * 500, MAX_BACKOFF_MS);
    const delay = base + Math.random() * 1000;

    this.reconnectTimer = window.setTimeout(() => this.connect(), delay);
  }

  private clearReconnect(): void {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = window.setInterval(() => {
      // The server reads to detect disconnects; this keeps intermediaries from
      // closing an idle connection.
      this.socket?.send('ping');
    }, HEARTBEAT_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }
}
