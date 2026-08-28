"""
流水线配置加载模块
从 pipeline_config.yaml 或环境变量加载配置
"""

import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

import yaml


@dataclass
class WorkerSpec:
    """一个 worker = 一种模型调用通道(本地 / 云端)。"""
    name: str                    # "local" / "cloud"
    model_name: str              # 传给 TA-CN 的 model_name
    timeout: int = 10800         # 单只股超时(秒)


@dataclass
class DispatchConfig:
    """并发调度策略配置。"""
    max_retry: int = 1           # 失败重入队次数(0=不重试;1=总共尝试 2 次)
    failure_threshold: int = 3   # 同一 worker 连续失败 N 次判本轮失效


@dataclass
class PipelineConfig:
    """流水线配置"""
    # TradingAgents-CN API
    api_base_url: str = "http://localhost:8000"
    api_username: str = ""
    api_password: str = ""

    # 分析参数
    batch_size: int = 1  # 串行分析，避免本地 LLM 并发资源争抢导致超时
    timeout_per_stock: int = 10800  # 3 小时/只（本地模型较慢，深度分析需要更长时间）

    # 报告
    report_output_dir: str = "./reports"
    server_port: int = 8222
    tradingagents_results_dir: str = "./TradingAgents-CN/results"

    # 筛选
    strategy: str = "b1"

    # TradingAgents 分析配置
    research_depth: str = "深度"
    selected_analysts: List[str] = field(
        default_factory=lambda: ["market", "fundamentals", "news", "social", "czsc", "yangjia"]
    )

    # 调度
    schedule_time: str = "01:00"
    skip_holidays: bool = True

    # 并发调度(消费者模型)
    workers: List[WorkerSpec] = field(default_factory=list)   # 模型 worker 列表
    dispatch: DispatchConfig = field(default_factory=DispatchConfig)


# 必需配置项列表
REQUIRED_FIELDS = ["api_username", "api_password"]


def load_config(config_path: Optional[str] = None) -> PipelineConfig:
    """
    加载配置，优先级：环境变量 > YAML 文件 > 默认值

    Args:
        config_path: YAML 配置文件路径，默认为 pipeline_config.yaml

    Returns:
        PipelineConfig 实例

    Raises:
        SystemExit: 缺少必需配置项时退出
    """
    if config_path is None:
        config_path = os.getenv("PIPELINE_CONFIG_PATH", "pipeline_config.yaml")

    # 从 YAML 文件加载
    yaml_config = {}
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
            if raw and isinstance(raw, dict):
                # 支持顶层 pipeline: 键或直接平铺
                yaml_config = raw.get("pipeline", raw)

    # 构建配置字典（YAML 值作为基础）
    config_dict = {}

    # 字段名到环境变量名的映射
    env_mapping = {
        "api_base_url": "PIPELINE_API_BASE_URL",
        "api_username": "PIPELINE_API_USERNAME",
        "api_password": "PIPELINE_API_PASSWORD",
        "batch_size": "PIPELINE_BATCH_SIZE",
        "timeout_per_stock": "PIPELINE_TIMEOUT_PER_STOCK",
        "report_output_dir": "PIPELINE_REPORT_OUTPUT_DIR",
        "server_port": "PIPELINE_SERVER_PORT",
        "tradingagents_results_dir": "PIPELINE_TA_RESULTS_DIR",
        "strategy": "PIPELINE_STRATEGY",
        "research_depth": "PIPELINE_RESEARCH_DEPTH",
        "schedule_time": "PIPELINE_SCHEDULE_TIME",
        "skip_holidays": "PIPELINE_SKIP_HOLIDAYS",
    }

    # 对每个字段：环境变量 > YAML > 默认值
    for field_name, env_name in env_mapping.items():
        env_val = os.getenv(env_name)
        if env_val is not None:
            config_dict[field_name] = env_val
        elif field_name in yaml_config:
            config_dict[field_name] = yaml_config[field_name]

    # selected_analysts 特殊处理（列表类型）
    env_analysts = os.getenv("PIPELINE_SELECTED_ANALYSTS")
    if env_analysts:
        config_dict["selected_analysts"] = [a.strip() for a in env_analysts.split(",")]
    elif "selected_analysts" in yaml_config:
        config_dict["selected_analysts"] = yaml_config["selected_analysts"]

    # workers 列表解析
    if "workers" in yaml_config:
        config_dict["workers"] = [
            WorkerSpec(**w) if isinstance(w, dict) else w
            for w in yaml_config["workers"]
        ]
    # dispatch 解析
    if "dispatch" in yaml_config and isinstance(yaml_config["dispatch"], dict):
        config_dict["dispatch"] = DispatchConfig(**yaml_config["dispatch"])

    # 类型转换
    if "batch_size" in config_dict:
        config_dict["batch_size"] = int(config_dict["batch_size"])
    if "timeout_per_stock" in config_dict:
        config_dict["timeout_per_stock"] = int(config_dict["timeout_per_stock"])
    if "server_port" in config_dict:
        config_dict["server_port"] = int(config_dict["server_port"])
    if "skip_holidays" in config_dict:
        val = config_dict["skip_holidays"]
        if isinstance(val, str):
            config_dict["skip_holidays"] = val.lower() in ("true", "1", "yes")

    # 创建配置实例
    config = PipelineConfig(**config_dict)

    # 校验必需配置项
    missing = []
    for req_field in REQUIRED_FIELDS:
        value = getattr(config, req_field, "")
        if not value:
            missing.append(req_field)

    if missing:
        print(f"[错误] 缺少必需配置项: {', '.join(missing)}", file=sys.stderr)
        print(f"请在 pipeline_config.yaml 或环境变量中配置以下项:", file=sys.stderr)
        for f in missing:
            env_name = env_mapping.get(f, f"PIPELINE_{f.upper()}")
            print(f"  - {f} (环境变量: {env_name})", file=sys.stderr)
        sys.exit(1)

    return config
