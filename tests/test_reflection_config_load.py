"""真实 pipeline_config.yaml 加载成 PipelineConfig 的验证。

前面的测试只验证了 dataclass 有字段和 yaml 有键，
这里验证加载器真的把 yaml 的值灌进了 dataclass。

注意：**不要断言开关当前是 true 还是 false** —— 它本来就是拿来翻的。
这里断言的是「dataclass 的值 == yaml 里的值」这个映射关系。
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, "/home/lima/workspace/stock")

from pipeline.config import load_config

ROOT = Path("/home/lima/workspace/stock")
CONFIG = ROOT / "pipeline_config.yaml"


@pytest.fixture
def cfg():
    return load_config(str(CONFIG))


@pytest.fixture
def raw_yaml():
    """load_config 取的是 yaml 的 pipeline 子块，reflection 嵌在里面。"""
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["pipeline"]


class TestRealConfigLoad:
    def test_配置文件能加载(self, cfg):
        assert cfg is not None

    def test_reflection开关与yaml一致(self, cfg, raw_yaml):
        assert cfg.reflection_enabled is bool(raw_yaml["reflection"]["enabled"])

    def test_延迟天数与yaml一致(self, cfg, raw_yaml):
        assert cfg.reflection_delay_days == int(raw_yaml["reflection"]["delay_days"])

    def test_既有配置未被破坏(self, cfg):
        assert cfg.mode in ("local", "local+remote")
        assert cfg.batch_size >= 1
        assert isinstance(cfg.workers, list)
        assert cfg.dispatch.max_retry >= 0


class TestToggleWorks:
    """改 yaml → 加载器如实反映。两个方向都要能翻。"""

    @staticmethod
    def _write_with(tmp_path, **overrides):
        data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        data["pipeline"]["reflection"].update(overrides)
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return load_config(str(p))

    def test_改成true能被读入(self, tmp_path):
        assert self._write_with(tmp_path, enabled=True).reflection_enabled is True

    def test_改成false能被读入(self, tmp_path):
        assert self._write_with(tmp_path, enabled=False).reflection_enabled is False

    def test_延迟天数改成3能被读入(self, tmp_path):
        assert self._write_with(tmp_path, delay_days=3).reflection_delay_days == 3

    def test_缺整块reflection时用默认值(self, tmp_path):
        data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        data["pipeline"].pop("reflection", None)
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        assert load_config(str(p)).reflection_enabled is False
