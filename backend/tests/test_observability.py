import sys

sys.path.insert(0, ".")

from app.core.observability import METRICS, metric_path, task_context, task_id_context


def test_metric_path_collapses_public_ids():
    assert metric_path("/api/v1/quizzes/generation-tasks/qtask_abc123") == "/api/v1/quizzes/generation-tasks/{id}"
    assert metric_path("/api/v1/health") == "/api/v1/health"


def test_metrics_render_prometheus_text_and_context():
    METRICS.reset()
    METRICS.counter("test_events_total", "Test events", {"kind": "unit"})
    METRICS.observe("test_duration_seconds", "Test duration", 0.2, {"kind": "unit"})
    output = METRICS.render()
    assert "# TYPE test_events_total counter" in output
    assert 'test_events_total{kind="unit"} 1' in output
    assert "test_duration_seconds_bucket" in output
    with task_context("qtask_test"):
        assert task_id_context.get() == "qtask_test"
    assert task_id_context.get() == "-"
    METRICS.reset()
