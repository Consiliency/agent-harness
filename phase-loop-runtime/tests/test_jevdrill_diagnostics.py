"""Closed diagnostic categories preserve fail-closed usage and discard raw data."""

import json
from dataclasses import replace

import pytest

from phase_loop_runtime import launcher
from test_jevdrill_usage import records, synthetic_spec


@pytest.mark.parametrize("line,reason", [
    ('PRIVATE_CREDENTIAL not json', 'malformed_record'),
    ('{"type":"PRIVATE_UNKNOWN"}', 'unsupported_event_sequence'),
    ('{"type":"item.completed","item":{"type":"PRIVATE_ITEM","message":"PRIVATE_OUTPUT"}}', 'ambiguous_item_or_collaboration'),
    ('{"type":"item.completed","item":{"type":"error","message":"model rerouted: PRIVATE_MODEL"}}', 'model_rerouted'),
    ('{"type":"item.completed","item":{"type":"error","message":"in-process app-server event stream lagged; dropped PRIVATE_VALUE"}}', 'announced_event_loss'),
    ('{"type":"item.completed","item":{"type":"collab_tool_call","payload":"PRIVATE_REASONING"}}', 'ambiguous_item_or_collaboration'),
    ('{"type":"turn.completed","usage":{"input_tokens":true}}', 'invalid_counter'),
    ('{"type":"turn.completed","usage":{"input_tokens":1,"cached_input_tokens":2}}', 'invalid_subset'),
    ('{"type":"turn.completed","usage":{"PRIVATE_KEY":3}}', 'unclassifiable_usage'),
    ('{"type":"item.completed","type":"PRIVATE_DUPLICATE"}', 'malformed_record'),
])
def test_fixed_first_rejection_and_privacy(line, reason):
    collector = launcher._CodexUsageCollector()
    for row in records()[:2] + [line] + records():
        collector.observe(row)
    collector.invalidate("reader_failure")
    diagnostic = collector.diagnostics()
    assert diagnostic["reason"] == reason and diagnostic["usage_valid"] is False
    assert collector.receipt() is None
    assert "PRIVATE_" not in json.dumps(diagnostic)
    assert sum(diagnostic["event_counts"].values()) <= 3


def test_benign_error_is_separate_from_tool_category_and_valid_usage():
    collector = launcher._CodexUsageCollector()
    warning = '{"type":"item.completed","item":{"type":"error","message":"PRIVATE_WARNING"}}'
    for line in records(middle=[warning]):
        collector.observe(line)
    diagnostic = collector.diagnostics()
    assert diagnostic["item_counts"] == {"error": 1}
    assert diagnostic["usage_valid"] is True and diagnostic["reason"] is None
    assert "PRIVATE_" not in json.dumps(diagnostic)


@pytest.mark.parametrize("reason", ["reader_failure", "incomplete_drain"])
def test_stream_failure_has_first_reason_precedence(reason):
    collector = launcher._CodexUsageCollector()
    for line in records():
        collector.observe(line)
    collector.invalidate(reason)
    collector.invalidate("malformed_record")
    assert collector.diagnostics()["reason"] == reason
    assert collector.receipt() is None


def test_zero_defaults_and_missing_terminal_have_distinct_unknown_reasons():
    collector = launcher._CodexUsageCollector()
    assert collector.diagnostics()["reason"] == "incomplete_terminal"
    for line in records({"input_tokens": 0, "output_tokens": 0}):
        collector.observe(line)
    assert collector.diagnostics()["reason"] == "zero_default"
    assert collector.receipt() is None


def test_real_launch_preserves_diagnostics_and_enrichment(tmp_path, monkeypatch):
    spec = synthetic_spec(tmp_path, monkeypatch)
    result = launcher.launch_with_spec(spec, codex_usage_capture=True)
    assert result.jevdrill_protocol_diagnostics["usage_valid"] is True
    assert launcher._result_with_spec(result, spec).jevdrill_protocol_diagnostics == result.jevdrill_protocol_diagnostics
    assert result.event_metadata()["jevdrill_protocol_diagnostics"] == result.jevdrill_protocol_diagnostics


def test_disabled_probe_and_ordinary_paths_are_distinct(tmp_path, monkeypatch):
    spec = synthetic_spec(tmp_path, monkeypatch, version="unsupported")
    result = launcher.launch_with_spec(spec, codex_usage_capture=True)
    assert result.jevdrill_protocol_diagnostics == {"capture": "disabled", "reason": "unsupported_path_or_probe"}
    assert launcher.launch_with_spec(spec).jevdrill_protocol_diagnostics is None
    assert launcher.launch_with_spec(spec, dry_run=True, codex_usage_capture=True).jevdrill_protocol_diagnostics is None


def test_announced_loss_survives_actual_launcher(tmp_path, monkeypatch):
    lines = records(middle=['{"type":"item.completed","item":{"type":"error","message":"in-process app-server event stream lagged; dropped 1 events"}}'])
    spec = synthetic_spec(tmp_path, monkeypatch, lines=lines)
    result = launcher.launch_with_spec(replace(spec, launch_timeout_seconds=10), codex_usage_capture=True)
    assert result.jevdrill_protocol_diagnostics["reason"] == "announced_event_loss"
    assert result.jevdrill_usage is None


def startup_records(item):
    lines = records()
    lines.insert(1, '{"type":"item.completed","item":' + item + '}')
    return lines


def test_startup_warnings_preserve_counter_semantics_and_privacy():
    collector = launcher._CodexUsageCollector()
    lines = startup_records('{"id":"PRIVATE_ID","type":"error","message":"PRIVATE_WARNING"}')
    lines.insert(2, lines[1])
    for line in lines:
        collector.observe(line)
    receipt = collector.receipt()
    assert receipt is not None
    assert {row["method"] for row in receipt["measurements"]} == {"codex_exec_jsonl_0_159_2_v2"}
    assert collector.diagnostics()["item_counts"] == {"error": 2}
    assert collector.diagnostics()["stage"] == 3
    assert "PRIVATE_" not in json.dumps([collector.diagnostics(), receipt])


@pytest.mark.parametrize("item,reason,category", [
    ('{"type":"error","message":"PRIVATE_WARNING"}', 'invalid_startup_warning', 'error'),
    ('{"id":false,"type":"error","message":"PRIVATE_WARNING"}', 'invalid_startup_warning', 'error'),
    ('{"id":"","type":"error","message":"PRIVATE_WARNING"}', 'invalid_startup_warning', 'error'),
    ('{"id":"0","type":"error","message":""}', 'invalid_startup_warning', 'error'),
    ('{"id":"0","type":"error","message":7}', 'ambiguous_error_attribution', 'error'),
    ('{"id":"0","id":"PRIVATE_DUPLICATE","type":"error","message":"PRIVATE_WARNING"}', 'invalid_startup_warning', 'error'),
    ('{"id":"0","type":"error","message":"PRIVATE_WARNING","message":"PRIVATE_DUPLICATE"}', 'ambiguous_error_attribution', 'error'),
    ('{"id":"0","type":"error","message":"PRIVATE_WARNING","PRIVATE_KEY":"PRIVATE_VALUE"}', 'invalid_startup_warning', 'error'),
    ('{"id":"0","type":"error","type":"PRIVATE_DUPLICATE","message":"PRIVATE_WARNING"}', 'ambiguous_item_or_collaboration', 'unknown'),
    ('{"id":"0","type":"PRIVATE_ITEM"}', 'ambiguous_item_or_collaboration', 'unknown'),
    ('{"id":"0","type":"command_execution"}', 'unsupported_event_sequence', 'command_execution'),
    ('{"id":"0","type":"web_search"}', 'unsupported_event_sequence', 'web_search'),
    ('{"id":"0","type":"agent_message"}', 'unsupported_event_sequence', 'agent_message'),
    ('{"id":"0","type":"collab_tool_call"}', 'ambiguous_item_or_collaboration', 'collab_tool_call'),
    ('{"id":"0","type":"error","message":"model rerouted: PRIVATE_MODEL"}', 'model_rerouted', 'error'),
    ('{"id":"0","type":"error","message":"in-process app-server event stream lagged; dropped PRIVATE_VALUE"}', 'announced_event_loss', 'error'),
])
def test_startup_invalid_items_are_classified_before_order_rejection(item, reason, category):
    collector = launcher._CodexUsageCollector()
    for line in startup_records(item):
        collector.observe(line)
    diagnostic = collector.diagnostics()
    assert collector.receipt() is None
    assert diagnostic["reason"] == reason
    assert diagnostic["stage"] == 1
    assert diagnostic["item_counts"] == {category: 1}
    assert "PRIVATE_" not in json.dumps(diagnostic)


@pytest.mark.parametrize("location", ["before_thread", "after_terminal", "started", "updated"])
def test_warning_order_still_requires_a_started_thread_and_completed_item(location):
    collector = launcher._CodexUsageCollector()
    lines = startup_records('{"id":"0","type":"error","message":"PRIVATE_WARNING"}')
    warning = lines.pop(1)
    if location == "before_thread":
        lines.insert(0, warning)
    elif location == "after_terminal":
        lines.append(warning)
    else:
        lines.insert(1, warning.replace('"item.completed"', '"item.' + location + '"'))
    for line in lines:
        collector.observe(line)
    assert collector.receipt() is None
    assert collector.diagnostics()["reason"] == "unsupported_event_sequence"
    assert collector.diagnostics()["item_counts"] == {"error": 1}


def test_startup_warning_does_not_supply_counters_or_hide_invalid_totals():
    lines = startup_records('{"id":"0","type":"error","message":"PRIVATE_WARNING"}')
    for usage, reason in [({"input_tokens": True}, "invalid_counter"), ({"input_tokens": 1, "cached_input_tokens": 2}, "invalid_subset"), ({"input_tokens": 0, "output_tokens": 0}, "zero_default")]:
        collector = launcher._CodexUsageCollector()
        for line in lines[:-1] + [json.dumps({"type":"turn.completed","usage":usage})]:
            collector.observe(line)
        assert collector.receipt() is None
        assert collector.diagnostics()["reason"] == reason
    collector = launcher._CodexUsageCollector()
    for line in lines[:-1]:
        collector.observe(line)
    assert collector.receipt() is None
    assert collector.diagnostics()["reason"] == "incomplete_terminal"


def test_startup_warning_survives_actual_launcher(tmp_path, monkeypatch):
    lines = startup_records('{"id":"PRIVATE_ID","type":"error","message":"PRIVATE_WARNING"}')
    result = launcher.launch_with_spec(synthetic_spec(tmp_path, monkeypatch, lines=lines), codex_usage_capture=True)
    assert result.jevdrill_usage is not None
    assert result.jevdrill_protocol_diagnostics["usage_valid"] is True
    assert result.jevdrill_protocol_diagnostics["item_counts"] == {"error": 1}
    assert "PRIVATE_" not in json.dumps(result.jevdrill_protocol_diagnostics)
