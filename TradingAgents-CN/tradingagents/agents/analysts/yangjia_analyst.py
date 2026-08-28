"""
养家视角分析师（炒股养家 · 交易操作系统）

基于炒股养家（林广昌）的完整思维框架，对真实K线和行情数据进行解读，
产出情绪周期研判、赢面评估、仓位建议等决策参考。

该分析师与 Market/Social/News/Fundamentals/CZSC 分析师并列，
作为第 6 位独立分析师加入 LangGraph 辩论系统。
不调用外部工具/API，直接读取本地 stock_data 目录的真实数据。
"""

import json
import os
from pathlib import Path
from typing import Optional

from tradingagents.utils.logging_init import get_logger

logger = get_logger("default")

# SKILL.md 路径查找
_SKILL_SEARCH_PATHS = [
    Path(__file__).resolve().parents[4] / "chaoguyangjia-perspective" / "SKILL.md",
    Path(".") / "chaoguyangjia-perspective" / "SKILL.md",
    Path("..") / "chaoguyangjia-perspective" / "SKILL.md",
]


def _load_skill_content() -> str:
    """加载 SKILL.md 完整内容"""
    env_path = os.getenv("YANGJIA_SKILL_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p.read_text(encoding="utf-8")

    for p in _SKILL_SEARCH_PATHS:
        if p.exists():
            logger.info(f"🎯 [养家分析师] 加载 SKILL.md: {p.resolve()}")
            return p.read_text(encoding="utf-8")

    logger.warning("⚠️ [养家分析师] SKILL.md 未找到，降级为通用短线框架")
    return _FALLBACK_SYSTEM_PROMPT


_FALLBACK_SYSTEM_PROMPT = """你是一位专注于中短期波段交易（1-3周）的交易顾问。
分析框架：情绪周期（冰点/复苏/发酵/高潮/退潮）+ 赢面评估 + 仓位管理。
赢面仓位表：<60%观望，60-70%小仓，70-80%中仓，>80%重仓。
输出要求：情绪阶段判断 → 赢面百分比 → 仓位建议 → 关键风险。"""


def _load_kline_data(ticker: str, stock_data_dir: str = "stock_data") -> Optional[list]:
    """从本地 stock_data/{code}_d.json 读取日K线数据"""
    code_with_suffix = ticker if "." in ticker else None
    code6 = ticker.split(".")[0] if "." in ticker else ticker

    data_dir = Path(stock_data_dir)
    if not data_dir.exists():
        search_paths = [
            Path(".") / "stock_data",
            Path("..") / "stock_data",
            Path(__file__).resolve().parents[4] / "stock_data",
        ]
        env_dir = os.getenv("STOCK_DATA_DIR")
        if env_dir:
            search_paths.insert(0, Path(env_dir))
        for candidate in search_paths:
            if candidate.exists():
                data_dir = candidate
                break

    # 查找文件
    candidates = []
    if data_dir.exists():
        for f in data_dir.iterdir():
            if f.name.startswith(code6) and f.name.endswith("_d.json") and "realtime" not in f.name:
                candidates.append(f)

    for file_path in candidates:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                file_data = json.load(f)
            kline_data = file_data.get("data", [])
            if kline_data and len(kline_data) >= 60:
                return kline_data
        except Exception:
            continue
    return None


def _load_realtime_data(ticker: str, stock_data_dir: str = "stock_data") -> Optional[dict]:
    """从本地 stock_data/{code}_realtime_d.json 读取实时行情"""
    code_with_suffix = ticker if "." in ticker else None
    code6 = ticker.split(".")[0] if "." in ticker else ticker

    data_dir = Path(stock_data_dir)
    if not data_dir.exists():
        search_paths = [
            Path(".") / "stock_data",
            Path("..") / "stock_data",
            Path(__file__).resolve().parents[4] / "stock_data",
        ]
        env_dir = os.getenv("STOCK_DATA_DIR")
        if env_dir:
            search_paths.insert(0, Path(env_dir))
        for candidate in search_paths:
            if candidate.exists():
                data_dir = candidate
                break

    # 查找 realtime 文件
    if data_dir.exists():
        for f in data_dir.iterdir():
            if f.name.startswith(code6) and "realtime" in f.name and f.name.endswith(".json"):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        file_data = json.load(fp)
                    data = file_data.get("data", {})
                    if isinstance(data, dict) and data.get("p"):
                        return data
                except Exception:
                    continue
    return None


def _extract_yangjia_signals(kline_data: list, realtime_data: Optional[dict]) -> dict:
    """
    从真实K线+实时行情提取养家框架关注的指标
    所有数字由Python计算，不让LLM推算
    """
    signals = {}

    closes = [row.get("c", 0) for row in kline_data if row.get("c")]
    highs = [row.get("h", 0) for row in kline_data if row.get("h")]
    lows = [row.get("l", 0) for row in kline_data if row.get("l")]
    volumes = [row.get("v", 0) for row in kline_data if row.get("v")]
    dates = [row.get("t", "") for row in kline_data]

    if not closes or len(closes) < 60:
        return {"error": "数据不足"}

    current_price = closes[-1]
    signals["当前价格"] = round(current_price, 2)
    signals["数据截止日"] = str(dates[-1])[:10] if dates else "未知"
    signals["K线天数"] = len(closes)

    # === 涨跌幅 ===
    if len(closes) >= 6:
        signals["5日涨幅%"] = round((closes[-1] / closes[-6] - 1) * 100, 2)
    if len(closes) >= 11:
        signals["10日涨幅%"] = round((closes[-1] / closes[-11] - 1) * 100, 2)
    if len(closes) >= 21:
        signals["20日涨幅%"] = round((closes[-1] / closes[-21] - 1) * 100, 2)

    # 当日涨幅
    if len(closes) >= 2:
        signals["当日涨幅%"] = round((closes[-1] / closes[-2] - 1) * 100, 2)

    # === 价格位置 ===
    recent_60_highs = highs[-60:]
    recent_60_lows = lows[-60:]
    high_60 = max(recent_60_highs)
    low_60 = min(recent_60_lows)
    price_range = high_60 - low_60
    if price_range > 0:
        position = (current_price - low_60) / price_range * 100
        signals["价格在60日区间位置%"] = round(position, 1)
        signals["距60日高点%"] = round((high_60 - current_price) / current_price * 100, 2)
        signals["距60日低点%"] = round((current_price - low_60) / current_price * 100, 2)
        # 赢面计算
        upside = (high_60 - current_price) / current_price * 100
        downside = (current_price - low_60) / current_price * 100
        signals["上方空间%(至60日高点)"] = round(upside, 2)
        signals["下方风险%(至60日低点)"] = round(downside, 2)
        signals["风险收益比"] = round(upside / downside, 2) if downside > 0 else 99
    signals["60日最高价"] = round(high_60, 2)
    signals["60日最低价"] = round(low_60, 2)

    # === 量能 ===
    if len(volumes) >= 5:
        avg_vol_5 = sum(volumes[-5:]) / 5
        if avg_vol_5 > 0:
            signals["当日成交量/5日均量"] = round(volumes[-1] / avg_vol_5, 2)
    if len(volumes) >= 20:
        avg_vol_20 = sum(volumes[-20:]) / 20
        if avg_vol_20 > 0:
            signals["当日成交量/20日均量"] = round(volumes[-1] / avg_vol_20, 2)

    # === 振幅 ===
    if highs and lows and closes:
        amplitude_today = (highs[-1] - lows[-1]) / closes[-2] * 100 if len(closes) >= 2 and closes[-2] > 0 else 0
        signals["当日振幅%"] = round(amplitude_today, 2)
        if len(highs) >= 5 and len(lows) >= 5:
            amplitudes = [(highs[-i] - lows[-i]) / closes[-i-1] * 100
                         for i in range(1, 6) if closes[-i-1] > 0]
            if amplitudes:
                signals["5日平均振幅%"] = round(sum(amplitudes) / len(amplitudes), 2)

    # === 连续涨跌天数 ===
    consecutive = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i-1]:
            if consecutive >= 0:
                consecutive += 1
            else:
                break
        elif closes[i] < closes[i-1]:
            if consecutive <= 0:
                consecutive -= 1
            else:
                break
        else:
            break
    signals["连续涨跌天数"] = consecutive  # 正=连涨，负=连跌

    # === 实时行情补充 ===
    if realtime_data:
        if realtime_data.get("hs"):
            signals["换手率%"] = realtime_data["hs"]
        if realtime_data.get("lb"):
            signals["量比"] = realtime_data["lb"]
        if realtime_data.get("zdf60"):
            signals["60日涨幅%"] = realtime_data["zdf60"]
        if realtime_data.get("zdfnc"):
            signals["年初至今涨幅%"] = realtime_data["zdfnc"]
        if realtime_data.get("pe"):
            signals["市盈率PE"] = realtime_data["pe"]

    return signals


def create_yangjia_analyst(llm, config: dict = None):
    """
    创建养家视角分析师节点

    Args:
        llm: LangChain LLM 实例
        config: 配置字典，可包含 stock_data_dir 键

    Returns:
        LangGraph 节点函数
    """
    config = config or {}
    stock_data_dir = config.get("stock_data_dir", "stock_data")

    # 启动时加载 SKILL.md
    SKILL_CONTENT = _load_skill_content()

    def yangjia_analyst_node(state) -> dict:
        logger.info("🎯 [养家分析师] ===== 养家视角分析师节点开始 =====")

        ticker = state["company_of_interest"]
        trade_date = state.get("trade_date", "")

        logger.info(f"🎯 [养家分析师] 分析标的: {ticker}, 交易日期: {trade_date}")

        # 1. 加载本地真实数据
        kline_data = _load_kline_data(ticker, stock_data_dir)
        if kline_data is None or len(kline_data) < 60:
            logger.warning(f"⚠️ [养家分析师] {ticker} K线数据不足，返回空报告")
            return {
                "yangjia_report": f"养家视角分析：{ticker} 本地K线数据不可用或不足（需至少60根日K线），跳过。"
            }

        realtime_data = _load_realtime_data(ticker, stock_data_dir)

        # 2. Python 计算指标
        signals = _extract_yangjia_signals(kline_data, realtime_data)
        if signals.get("error"):
            return {
                "yangjia_report": f"养家视角分析：{ticker} 数据提取异常（{signals['error']}），跳过。"
            }

        logger.info(f"🎯 [养家分析师] 指标提取完成: 价格={signals.get('当前价格')}, "
                   f"5日涨幅={signals.get('5日涨幅%')}%, "
                   f"风险收益比={signals.get('风险收益比')}")

        # 3. LLM 用养家框架解读数据
        signals_text = json.dumps(signals, ensure_ascii=False, indent=2)

        user_prompt = f"""以下是股票 {ticker} 的真实市场数据（由系统计算，非推测）：

{signals_text}

请基于以上真实数据，用你的交易框架给出分析：
1. 情绪阶段判断（基于量能变化和涨跌趋势推断个股情绪状态）
2. 赢面评估（基于风险收益比，给出具体百分比）
3. 仓位建议（参照你的赢面仓位表）
4. 空仓测试（如果现在空仓，你会买入吗？为什么？）
5. 关键风险提示

注意：
- 所有数字已由系统计算，请直接引用，不要重新估算
- 你只能看到个股数据，无法看到全市场涨停家数等全市场情绪数据
- 使用人民币(¥)作为价格单位
- 持仓周期参考：1-3周波段"""

        try:
            response = llm.invoke([
                {"role": "system", "content": SKILL_CONTENT},
                {"role": "user", "content": user_prompt},
            ])
            report = response.content
            logger.info(f"🎯 [养家分析师] 报告生成完成，长度: {len(report)}")
            return {"yangjia_report": report}

        except Exception as e:
            logger.error(f"❌ [养家分析师] LLM 调用失败: {e}")
            # 降级：模板化报告
            return {"yangjia_report": _generate_fallback_report(ticker, signals)}

    return yangjia_analyst_node


def _generate_fallback_report(ticker: str, signals: dict) -> str:
    """LLM 不可用时的降级报告"""
    rr = signals.get("风险收益比", 0)
    if rr >= 3:
        winrate = "70-80%"
        position = "中仓（逐步建仓）"
    elif rr >= 1.5:
        winrate = "60-70%"
        position = "小仓（试探性参与）"
    else:
        winrate = "<60%"
        position = "观望（风险收益比不佳）"

    return f"""# 养家视角分析（降级报告）

## 基本数据
- 当前价格: ¥{signals.get('当前价格', 'N/A')}
- 5日涨幅: {signals.get('5日涨幅%', 'N/A')}%
- 风险收益比: {rr}
- 60日区间位置: {signals.get('价格在60日区间位置%', 'N/A')}%

## 赢面评估
- 预估赢面: {winrate}
- 仓位建议: {position}

注：本报告由模板自动生成（LLM不可用），仅供参考。
"""
