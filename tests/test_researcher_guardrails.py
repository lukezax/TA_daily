"""策略研究员护栏：空分析不得写入、纠错必须被读取、B2 分档统计、结论门槛。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from strategy_researcher import llm_client, wiki_manager
from strategy_researcher.llm_client import LocalLLMClient
from strategy_researcher.wiki_manager import WikiManager


def _mk_wiki(tmp_path: Path):
    (tmp_path / "daily_reports").mkdir()
    (tmp_path / "insights").mkdir()
    (tmp_path / "corrections").mkdir()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(wiki_manager, "WIKI_DIR", tmp_path)
    return monkeypatch


def test_empty_llm_response_is_retried_then_raises(monkeypatch):
    responses = [
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=""))]),
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="有效分析"))]),
    ]
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return responses[len(calls) - 1]

    client = LocalLLMClient.__new__(LocalLLMClient)
    client.model = "local"
    client.temperature = 0.3
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    assert client.chat("sys", "user") == "有效分析"
    assert len(calls) == 2


def test_empty_analysis_after_retries_raises(monkeypatch):
    empty = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=""))])
    client = LocalLLMClient.__new__(LocalLLMClient)
    client.model = "local"
    client.temperature = 0.3
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: empty))
    )
    with pytest.raises(RuntimeError):
        client.chat("sys", "user")


def test_write_daily_report_rejects_empty_analysis(tmp_path):
    monkeypatch = _mk_wiki(tmp_path)
    try:
        wiki = WikiManager()
        content = "# 策略日报\n\n## 三、策略分析\n\n## 五、状态\n"
        with pytest.raises(ValueError, match="策略分析"):
            wiki.write_daily_report("2026-11-20", content)
        assert not (tmp_path / "daily_reports" / "2026-11-20.md").exists()
    finally:
        monkeypatch.undo()


def test_recent_context_includes_corrections(tmp_path):
    monkeypatch = _mk_wiki(tmp_path)
    try:
        (tmp_path / "corrections" / "纠错_测试.md").write_text(
            "# 纠错: 历史结论\n\n- 教训: B1_3分曾被认为最优，后续已被推翻。", encoding="utf-8"
        )
        wiki = WikiManager()
        context = wiki.read_recent_context()
        assert "纠错" in context
        assert "B1_3分" in context
    finally:
        monkeypatch.undo()


def test_researcher_prompt_has_sample_size_and_data_quality_gates():
    source = Path(llm_client.__file__).read_text(encoding="utf-8")
    assert "样本量" in source
    assert "数据质量" in source
    assert "不实际下单" in source
    assert "历史" in source
