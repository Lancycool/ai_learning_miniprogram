"""Small, dependency-free observability primitives for the API and workers."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
task_id_context: ContextVar[str] = ContextVar("task_id", default="-")


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


@contextmanager
def task_context(task_id: str) -> Iterator[None]:
    token = task_id_context.set(task_id or "-")
    try:
        yield
    finally:
        task_id_context.reset(token)


_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")
_DYNAMIC_PATH = re.compile(r"/(?:qtask|ktrace|claim|kb|doc|ver|task|bank|quiz|attempt)_[A-Za-z0-9_-]+|/[0-9a-f]{16,}", re.I)


def accepted_request_id(value: str | None) -> str:
    return value if value and _REQUEST_ID.fullmatch(value) else new_request_id()


def metric_path(path: str) -> str:
    """Collapse public identifiers so metrics labels stay bounded."""
    return _DYNAMIC_PATH.sub("/{id}", path)


class JsonFormatter(logging.Formatter):
    _reserved = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(),
            "task_id": task_id_context.get(),
        }
        for key, value in record.__dict__.items():
            if key not in self._reserved and not key.startswith("_"):
                try:
                    json.dumps(value)
                    payload[key] = value
                except TypeError:
                    payload[key] = str(value)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    if any(getattr(handler, "_bamboo_json", False) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler._bamboo_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)


@dataclass
class Histogram:
    count: float = 0
    total: float = 0
    buckets: dict[float, int] | None = None


class MetricsRegistry:
    """Prometheus text exposition without a runtime dependency."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], Histogram] = {}
        self._definitions: dict[str, tuple[str, str]] = {}

    @staticmethod
    def _labels(labels: dict[str, object] | None) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((key, str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")) for key, value in (labels or {}).items()))

    def counter(self, name: str, help_text: str, labels: dict[str, object] | None = None, value: float = 1) -> None:
        key = (name, self._labels(labels))
        with self._lock:
            self._definitions.setdefault(name, ("counter", help_text))
            self._counters[key] = self._counters.get(key, 0) + value

    def observe(self, name: str, help_text: str, value: float, labels: dict[str, object] | None = None) -> None:
        key = (name, self._labels(labels))
        with self._lock:
            self._definitions.setdefault(name, ("histogram", help_text))
            item = self._histograms.setdefault(key, Histogram(buckets={b: 0 for b in (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300)}))
            item.count += 1
            item.total += value
            for bucket in item.buckets or {}:
                if value <= bucket:
                    item.buckets[bucket] += 1

    @staticmethod
    def _label_text(labels: tuple[tuple[str, str], ...], extra: tuple[str, str] | None = None) -> str:
        values = list(labels)
        if extra:
            values.append(extra)
        if not values:
            return ""
        return "{" + ",".join(f'{key}="{value}"' for key, value in values) + "}"

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            definitions = dict(self._definitions)
            counters = dict(self._counters)
            histograms = dict(self._histograms)
        for name, (kind, help_text) in sorted(definitions.items()):
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} {kind}")
            if kind == "counter":
                for (metric, labels), value in sorted(counters.items()):
                    lines.append(f"{metric}{self._label_text(labels)} {value:g}")
            else:
                for (metric, labels), item in sorted(histograms.items()):
                    for bucket, value in (item.buckets or {}).items():
                        lines.append(f"{metric}_bucket{self._label_text(labels, ("le", str(bucket)))} {value}")
                    lines.append(f"{metric}_bucket{self._label_text(labels, ("le", "+Inf"))} {int(item.count)}")
                    lines.append(f"{metric}_count{self._label_text(labels)} {int(item.count)}")
                    lines.append(f"{metric}_sum{self._label_text(labels)} {item.total:g}")
        return "\n".join(lines) + ("\n" if lines else "")

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()
            self._definitions.clear()


METRICS = MetricsRegistry()


def record_task_created(private: bool) -> None:
    METRICS.counter("quiz_task_created_total", "Number of quiz generation tasks created", {"scope": "private" if private else "normal"})


def record_task_finished(status: str, private: bool, duration_seconds: float) -> None:
    labels = {"scope": "private" if private else "normal", "status": status}
    METRICS.counter("quiz_task_finished_total", "Number of quiz generation tasks finished", labels)
    METRICS.observe("quiz_task_duration_seconds", "Quiz generation task duration in seconds", duration_seconds, {"scope": labels["scope"]})


def record_task_queue_wait(seconds: float, private: bool) -> None:
    METRICS.observe("quiz_task_queue_wait_seconds", "Time spent waiting for a quiz worker", seconds, {"scope": "private" if private else "normal"})


def record_knowledge_retrieval(status: str, duration_seconds: float) -> None:
    METRICS.counter("knowledge_retrieval_total", "Number of private knowledge retrieval generations", {"status": status})
    METRICS.observe("knowledge_retrieval_duration_seconds", "Private knowledge retrieval generation duration in seconds", duration_seconds, {"status": status})


def record_web_search(status: str, duration_seconds: float) -> None:
    METRICS.counter("web_search_total", "Number of web search attempts", {"status": status})
    METRICS.observe("web_search_duration_seconds", "Web search duration in seconds", duration_seconds, {"status": status})


def record_http_request(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    labels = {"method": method, "path": path, "status": status_code}
    METRICS.counter("http_requests_total", "Number of HTTP requests", labels)
    METRICS.observe("http_request_duration_seconds", "HTTP request duration in seconds", duration_seconds, {"method": method, "path": path})


def monotonic_seconds() -> float:
    return time.monotonic()
