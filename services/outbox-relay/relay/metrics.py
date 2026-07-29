"""Relay metrics, exposed on its own port.

Each service scrapes separately rather than reporting into a shared store: that
is the Prometheus pull model, and it means a dead relay shows up as a scrape
failure rather than as silence that looks like zero traffic.
"""

from prometheus_client import Counter, Gauge, Histogram, start_http_server

events_published_total = Counter(
    "relay_events_published_total",
    "Events successfully published to Kafka",
    ["event_type", "topic"],
)

events_failed_total = Counter(
    "relay_events_failed_total",
    "Publish attempts that failed",
    ["event_type"],
)

outbox_backlog = Gauge(
    "relay_outbox_backlog",
    "Unpublished rows remaining in the outbox",
)

outbox_oldest_age_seconds = Gauge(
    "relay_outbox_oldest_age_seconds",
    "Age of the oldest unpublished row",
)

publish_seconds = Histogram(
    "relay_publish_seconds",
    "Time to publish one event",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.5, 1.0, 5.0),
)


def serve(port: int) -> None:
    start_http_server(port)
