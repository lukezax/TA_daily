"""策略研究员配置"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env
_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / "TradingAgents-CN" / ".env", override=True)

RESEARCHER_CONFIG = {
    # LLM（本地 llama.cpp）
    "llm_base_url": "http://127.0.0.1:8080/v1",
    "llm_model": "local",
    "llm_timeout": 300,
    "llm_temperature": 0.3,

    # Tavily
    "tavily_api_key": os.getenv("TAVILY_API_KEY", ""),
    "tavily_max_results": 3,

    # 调度
    "schedule_time": "10:00",
    "hold_days": 3,  # 跨天验证默认持有天数

    # Wiki
    "wiki_dir": str(_project_root / "strategy_wiki"),

    # 上下文
    "context_days": 3,  # 读取最近几天报告作为上下文

    # 数据源
    "reports_dir": str(_project_root / "reports"),
    "results_dir": str(_project_root / "TradingAgents-CN" / "results"),
    "stock_data_dir": str(_project_root / "stock_data"),
}
