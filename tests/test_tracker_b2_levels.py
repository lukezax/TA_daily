"""跨天验证必须区分 B2 严格/宽松，不能合并成 B2_0分。"""

import json
from pathlib import Path

from strategy_researcher import cross_day_tracker as cdt


def _setup(tmp_path, monkeypatch):
    verified = tmp_path / "verified"
    verified.mkdir()
    monkeypatch.setattr(cdt, "PENDING_FILE", tmp_path / "pending.json")
    monkeypatch.setattr(cdt, "VERIFIED_DIR", verified)
    return cdt.CrossDayTracker()


def test_b2_signal_keeps_strict_tag(tmp_path, monkeypatch):
    tracker = _setup(tmp_path, monkeypatch)
    tracker.record_today_signals(
        None,
        {"signals": [{"code": "000001.SZ", "name": "测试", "price": 10.0, "tags": ["B2严格"]}]},
    )
    records = tracker._load_pending()
    assert records[0]["tags"] == ["B2严格"]


def test_performance_separates_b2_strict_and_loose(tmp_path, monkeypatch):
    tracker = _setup(tmp_path, monkeypatch)
    records = [
        {"strategy": "B2", "score": 0, "tags": ["B2严格"], "return_pct": 5.0},
        {"strategy": "B2", "score": 0, "tags": ["B2宽松"], "return_pct": 1.0},
    ]
    (tmp_path / "verified" / "2026-11-20.json").write_text(
        json.dumps(records, ensure_ascii=False), encoding="utf-8"
    )
    summary = tracker.get_performance_summary()
    assert "B2严格_0分" in summary["by_strategy"]
    assert "B2宽松_0分" in summary["by_strategy"]
    assert "B2_0分" not in summary["by_strategy"]
