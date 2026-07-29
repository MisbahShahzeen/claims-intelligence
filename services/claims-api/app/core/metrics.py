"""Application metrics.

HTTP metrics come free from the instrumentator. These are the domain ones - the
numbers an operator would alert on or explain to a stakeholder.

Naming follows Prometheus convention: counters end in _total, durations in
_seconds, and units are always base units. Grafana assumes this and will label
axes wrong otherwise.
"""

from prometheus_client import Counter, Gauge, Histogram

claims_submitted_total = Counter(
    "claims_submitted_total",
    "Claims accepted through FNOL intake",
    ["loss_type"],
)

claim_transitions_total = Counter(
    "claims_transitions_total",
    "Claim status transitions performed",
    ["from_status", "to_status", "actor_type"],
)

claim_transitions_rejected_total = Counter(
    "claims_transitions_rejected_total",
    "Transitions refused by the state machine",
    ["from_status", "to_status", "outcome"],
)

login_attempts_total = Counter(
    "claims_login_attempts_total",
    "Login attempts by result",
    ["result"],
)

websocket_connections = Gauge(
    "claims_websocket_connections",
    "Live WebSocket connections on this process",
)

outbox_backlog = Gauge(
    "claims_outbox_backlog",
    "Unpublished rows in the outbox",
)

event_processing_seconds = Histogram(
    "claims_event_processing_seconds",
    "Time to handle a consumed event",
    ["event_type"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0),
)
