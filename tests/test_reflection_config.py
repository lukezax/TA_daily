"""reflection 配置项的加载测试。"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, "/home/lima/workspace/stock")

from pipeline.config import PipelineConfig

CONFIG_PATH = Path("/home/lima/workspace/stock/pipeline_config.yaml")


class TestReflectionConfigField:
    def test_配置类有reflection_enabled字段(self):
        assert hasattr(PipelineConfig(), "reflection_enabled")

    def test_默认关闭(self):
        assert PipelineConfig().reflection_enabled is False


class TestYamlParsing:
    def test_配置文件能解析出开关(self):
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        assert "reflection" in raw["pipeline"], "pipeline 段缺少 reflection 配置"

    def test_开关是布尔值(self):
        """不要断言当前值 —— 开关本来就是要被翻的，只断言类型与存在性。"""
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        assert isinstance(raw["pipeline"]["reflection"]["enabled"], bool)

    def test_延迟天数默认为1(self):
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        assert raw["pipeline"]["reflection"]["delay_days"] == 1