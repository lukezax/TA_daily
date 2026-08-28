"""
缠论（CZSC）分析师节点

基于缠中说禅理论，对股票K线数据进行结构化分析，
产出分型/笔/中枢/买卖点等确定性技术信号，并用 LLM 生成可读报告。

该分析师与现有 Market/Social/News/Fundamentals 分析师并列，
作为第 5 位独立分析师加入 LangGraph 辩论系统。
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger

logger = get_logger("default")

# CZSC 包是否可用（运行时检测）
_CZSC_AVAILABLE = False
try:
    from czsc import CZSC, format_standard_kline, Freq, Direction

    _CZSC_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ [CZSC分析师] czsc 包未安装，缠论分析将降级为空报告")


def _load_kline_data(ticker: str, stock_data_dir: str = "stock_data") -> Optional[list]:
    """
    从本地 stock_data/{code}_d.json 读取日K线数据

    Args:
        ticker: 股票代码（6位纯数字或带后缀如 000519.SZ）
        stock_data_dir: stock_data 目录路径

    Returns:
        K线数据列表（智途API格式），或 None（文件不存在/数据不足）
    """
    # 支持带后缀和不带后缀的代码
    code_with_suffix = ticker if "." in ticker else None

    data_dir = Path(stock_data_dir)
    if not data_dir.exists():
        # 尝试从多个可能的路径查找 stock_data 目录
        search_paths = [
            Path(".") / "stock_data",           # 当前工作目录
            Path("..") / "stock_data",          # 上级目录（TradingAgents-CN -> workspace root）
            Path(__file__).resolve().parents[4] / "stock_data",  # 基于文件位置的推断
        ]
        # 也支持通过环境变量覆盖
        env_dir = os.getenv("STOCK_DATA_DIR")
        if env_dir:
            search_paths.insert(0, Path(env_dir))

        for candidate in search_paths:
            if candidate.exists():
                data_dir = candidate
                logger.info(f"📐 [CZSC分析师] 找到 stock_data 目录: {data_dir.resolve()}")
                break

    # 尝试多种文件名格式
    candidates = []
    if code_with_suffix:
        candidates.append(data_dir / f"{code_with_suffix}_d.json")
    # 纯6位数字也尝试
    code6 = ticker.split(".")[0] if "." in ticker else ticker
    # 遍历目录找匹配的文件
    if data_dir.exists():
        for f in data_dir.iterdir():
            if f.name.startswith(code6) and f.name.endswith("_d.json") and not "realtime" in f.name:
                if f not in candidates:
                    candidates.append(f)

    for file_path in candidates:
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    file_data = json.load(f)
                kline_data = file_data.get("data", [])
                if kline_data and len(kline_data) >= 120:
                    logger.info(
                        f"📐 [CZSC分析师] 加载K线数据: {file_path.name}, {len(kline_data)} 根K线"
                    )
                    return kline_data
                else:
                    logger.warning(
                        f"⚠️ [CZSC分析师] K线数据不足: {file_path.name}, {len(kline_data)} 根 (需>=120)"
                    )
            except Exception as e:
                logger.warning(f"⚠️ [CZSC分析师] 读取K线文件失败: {file_path} - {e}")

    return None


def _convert_to_bars(kline_data: list, ticker: str):
    """
    将智途API格式的K线数据转换为 CZSC RawBar 列表

    智途格式: {t, o, h, l, c, v, a, pc, sf}
    CZSC需要: DataFrame with columns [dt, symbol, open, close, high, low, vol, amount]
    """
    import pandas as pd

    code6 = ticker.split(".")[0] if "." in ticker else ticker

    records = []
    for row in kline_data:
        trade_time = row.get("t", "")
        if not trade_time:
            continue
        records.append({
            "dt": trade_time,
            "symbol": code6,
            "open": float(row.get("o", 0)),
            "close": float(row.get("c", 0)),
            "high": float(row.get("h", 0)),
            "low": float(row.get("l", 0)),
            "vol": float(row.get("v", 0)),
            "amount": float(row.get("a", 0) or 0),
        })

    df = pd.DataFrame(records)
    bars = format_standard_kline(df, freq="日线")
    return bars


def _extract_czsc_signals(czsc_obj) -> dict:
    """
    从 CZSC 对象中提取对投资决策有用的结构化信号

    Returns:
        包含缠论关键信号的字典
    """
    signals = {}

    bi_list = czsc_obj.bi_list
    fx_list = czsc_obj.fx_list

    # 1. 基本统计
    signals["bi_count"] = len(bi_list)
    signals["fx_count"] = len(fx_list)

    # 2. 当前笔的状态
    if bi_list:
        last_bi = bi_list[-1]
        signals["current_bi_direction"] = (
            "up" if str(last_bi.direction) in ("Direction.Up", "up", "Up") else "down"
        )
        signals["last_bi_high"] = round(float(last_bi.high), 2)
        signals["last_bi_low"] = round(float(last_bi.low), 2)
        signals["last_bi_length"] = int(last_bi.length) if hasattr(last_bi, "length") else 0

    # 3. 最近几根笔的趋势
    if len(bi_list) >= 3:
        recent_bis = bi_list[-5:] if len(bi_list) >= 5 else bi_list[-3:]
        highs = [float(b.high) for b in recent_bis]
        lows = [float(b.low) for b in recent_bis]
        # 判断趋势：高点逐步抬高=上升趋势
        up_highs = all(highs[i] <= highs[i + 1] for i in range(len(highs) - 1))
        up_lows = all(lows[i] <= lows[i + 1] for i in range(len(lows) - 1))
        down_highs = all(highs[i] >= highs[i + 1] for i in range(len(highs) - 1))
        down_lows = all(lows[i] >= lows[i + 1] for i in range(len(lows) - 1))

        if up_highs and up_lows:
            signals["trend"] = "上升趋势"
        elif down_highs and down_lows:
            signals["trend"] = "下降趋势"
        else:
            signals["trend"] = "震荡"
    else:
        signals["trend"] = "数据不足"

    # 4. 中枢识别（从笔序列中推导）
    # CZSC 对象可能有 zs_list 属性（取决于版本）
    zs_list = getattr(czsc_obj, "zs_list", [])
    if zs_list:
        last_zs = zs_list[-1]
        signals["zs_count"] = len(zs_list)
        signals["nearest_zs_high"] = round(float(getattr(last_zs, "zg", getattr(last_zs, "high", 0))), 2)
        signals["nearest_zs_low"] = round(float(getattr(last_zs, "zd", getattr(last_zs, "low", 0))), 2)
    else:
        # 手动从笔中推导近似中枢
        signals["zs_count"] = 0
        if len(bi_list) >= 3:
            # 最近3根笔的重叠区间近似为中枢
            recent3 = bi_list[-3:]
            overlap_high = min(float(b.high) for b in recent3)
            overlap_low = max(float(b.low) for b in recent3)
            if overlap_high > overlap_low:
                signals["nearest_zs_high"] = round(overlap_high, 2)
                signals["nearest_zs_low"] = round(overlap_low, 2)
                signals["zs_count"] = 1

    # 5. 支撑位和阻力位
    if bi_list:
        all_highs = [float(b.high) for b in bi_list[-10:]]
        all_lows = [float(b.low) for b in bi_list[-10:]]
        signals["resistance"] = round(max(all_highs), 2)
        signals["support"] = round(min(all_lows), 2)

    # 6. 买卖点判断（简化版）
    signals["buy_signals"] = []
    signals["sell_signals"] = []

    if len(bi_list) >= 5 and signals.get("nearest_zs_low") and signals.get("nearest_zs_high"):
        last_price = float(bi_list[-1].high + bi_list[-1].low) / 2
        zs_low = signals["nearest_zs_low"]
        zs_high = signals["nearest_zs_high"]

        # 一买：价格跌破中枢下沿后回升
        if last_price > zs_low and any(float(b.low) < zs_low for b in bi_list[-3:]):
            signals["buy_signals"].append("疑似一买（跌破中枢后回升）")

        # 二买：回踩不破中枢下沿
        if last_price > zs_low and float(bi_list[-1].low) >= zs_low * 0.98:
            if signals["current_bi_direction"] == "up":
                signals["buy_signals"].append("疑似二买（回踩中枢下沿不破后上涨）")

        # 三买：突破中枢上沿后回踩不破
        if last_price > zs_high and float(bi_list[-1].low) >= zs_high * 0.98:
            signals["buy_signals"].append("疑似三买（突破中枢后回踩不破上沿）")

        # 卖点判断
        if last_price < zs_high and any(float(b.high) > zs_high for b in bi_list[-3:]):
            signals["sell_signals"].append("疑似一卖（突破中枢后回落）")

        if signals["current_bi_direction"] == "down" and last_price < zs_high:
            if float(bi_list[-1].high) <= zs_high * 1.02:
                signals["sell_signals"].append("疑似二卖（反弹不过中枢上沿后下跌）")

    # 7. 趋势评分 (1-10)
    score = 5  # 中性基础分
    if signals.get("trend") == "上升趋势":
        score += 2
    elif signals.get("trend") == "下降趋势":
        score -= 2
    if signals.get("buy_signals"):
        score += min(len(signals["buy_signals"]), 2)
    if signals.get("sell_signals"):
        score -= min(len(signals["sell_signals"]), 2)
    if signals.get("current_bi_direction") == "up":
        score += 1
    elif signals.get("current_bi_direction") == "down":
        score -= 1
    signals["trend_score"] = max(1, min(10, score))

    return signals


def _generate_czsc_report(llm, ticker: str, signals: dict, company_name: str = "") -> str:
    """
    用 LLM 将 CZSC 结构化信号翻译为可读的缠论分析报告

    Args:
        llm: LangChain LLM 实例
        ticker: 股票代码
        signals: _extract_czsc_signals 的输出
        company_name: 公司名称

    Returns:
        Markdown 格式的缠论分析报告
    """
    signals_json = json.dumps(signals, ensure_ascii=False, indent=2)

    prompt = f"""你是一位精通缠论（缠中说禅理论）的技术分析师。请基于以下缠论量化分析结果，为股票 {company_name or ticker}（代码：{ticker}）生成一份专业的缠论结构分析报告。

## 缠论量化信号数据

{signals_json}

## 输出要求

请按以下格式生成报告（使用中文，纯 Markdown 格式，不使用 emoji）：

# 缠论结构分析报告

## 一、当前缠论结构

- 当前笔方向：[上涨/下跌]
- 笔数量：[N] 根
- 当前趋势判断：[上升趋势/下降趋势/震荡]
- 中枢数量：[N] 个
- 最近中枢区间：[低点 - 高点]

## 二、买卖点分析

- 买入信号：[列出所有买点信号，无则注明"暂无明确买点信号"]
- 卖出信号：[列出所有卖点信号，无则注明"暂无明确卖点信号"]

## 三、支撑与阻力

- 支撑位：[价格]
- 阻力位：[价格]

## 四、趋势评分

- 综合评分：[1-10 分]
- 评分说明：[简要解释评分依据]

## 五、操作建议

基于缠论结构分析，给出明确的技术面操作建议（买入/持有/观望/减仓），并说明理由。

注意事项：
- 缠论的笔确认需要后续K线验证，信号有一定滞后性
- 买点/卖点判断是基于简化规则，仅供参考
- 请结合趋势评分和当前笔方向给出建议
- 所有价格请使用人民币（¥）表示
"""

    try:
        response = llm.invoke([{"role": "user", "content": prompt}])
        report = response.content
        logger.info(f"📐 [CZSC分析师] LLM报告生成完成，长度: {len(report)}")
        return report
    except Exception as e:
        logger.error(f"❌ [CZSC分析师] LLM报告生成失败: {e}")
        # 降级：使用模板化文本
        return _generate_fallback_report(ticker, signals, company_name)


def _generate_fallback_report(ticker: str, signals: dict, company_name: str = "") -> str:
    """LLM 不可用时的降级报告（纯模板化文本）"""
    direction_cn = "上涨" if signals.get("current_bi_direction") == "up" else "下跌"
    trend = signals.get("trend", "未知")
    score = signals.get("trend_score", 5)
    buy_sigs = "、".join(signals.get("buy_signals", [])) or "暂无"
    sell_sigs = "、".join(signals.get("sell_signals", [])) or "暂无"
    support = signals.get("support", "N/A")
    resistance = signals.get("resistance", "N/A")
    zs_high = signals.get("nearest_zs_high", "N/A")
    zs_low = signals.get("nearest_zs_low", "N/A")

    return f"""# 缠论结构分析报告

## 一、当前缠论结构

- 当前笔方向：{direction_cn}
- 笔数量：{signals.get('bi_count', 0)} 根
- 当前趋势判断：{trend}
- 中枢数量：{signals.get('zs_count', 0)} 个
- 最近中枢区间：¥{zs_low} - ¥{zs_high}

## 二、买卖点分析

- 买入信号：{buy_sigs}
- 卖出信号：{sell_sigs}

## 三、支撑与阻力

- 支撑位：¥{support}
- 阻力位：¥{resistance}

## 四、趋势评分

- 综合评分：{score}/10

## 五、操作建议

（注：本报告由模板自动生成，LLM 分析不可用，仅供参考。）
"""


def _override_score_in_report(report: str, score: int) -> str:
    """
    强制将报告中的"综合评分"替换为脚本计算的 trend_score。

    报告内容（买卖点/支撑阻力/操作建议）完全保留，仅分数行以脚本分为准，
    避免 LLM 自由发挥导致评分与脚本不一致。

    Args:
        report: LLM 或 fallback 生成的报告文本
        score: 脚本计算的 trend_score（1-10）

    Returns:
        分数行已覆盖的报告文本
    """
    if not report:
        return report

    # 匹配 "综合评分" 行（兼容各种格式：综合评分：7 / 综合评分: 7分 / 综合评分：7/10 等）
    score_line_pattern = re.compile(r"[^\n]*综合评分[^\n：:]{0,4}[：:]\s*[^\n]*")
    new_line = f"- 综合评分：{score}/10"

    if score_line_pattern.search(report):
        return score_line_pattern.sub(new_line, report, count=1)

    # LLM 未输出评分行 → 在报告末尾追加
    return report.rstrip() + f"\n\n- 综合评分：{score}/10\n"


def create_czsc_analyst(llm, config: dict = None):
    """
    创建缠论分析师节点函数

    Args:
        llm: LangChain LLM 实例（用于生成可读报告）
        config: 配置字典，可包含 stock_data_dir 键

    Returns:
        LangGraph 节点函数
    """
    config = config or {}
    stock_data_dir = config.get("stock_data_dir", "stock_data")

    def czsc_analyst_node(state) -> dict:
        logger.info("📐 [CZSC分析师] ===== 缠论分析师节点开始 =====")

        ticker = state["company_of_interest"]
        trade_date = state.get("trade_date", "")

        logger.info(f"📐 [CZSC分析师] 分析标的: {ticker}, 交易日期: {trade_date}")

        # 检查 CZSC 是否可用
        if not _CZSC_AVAILABLE:
            logger.warning("⚠️ [CZSC分析师] czsc 包未安装，返回空报告")
            return {
                "czsc_report": "缠论分析：czsc 包未安装，跳过缠论结构分析。",
                "czsc_signals": "{}",
            }

        # 1. 加载K线数据
        kline_data = _load_kline_data(ticker, stock_data_dir)
        if kline_data is None:
            logger.warning(f"⚠️ [CZSC分析师] {ticker} K线数据不可用或不足，返回空报告")
            return {
                "czsc_report": f"缠论分析：{ticker} 的本地K线数据不可用或数据量不足（需至少120根日K线），跳过缠论结构分析。",
                "czsc_signals": "{}",
            }

        try:
            # 2. 转换为 CZSC 格式
            bars = _convert_to_bars(kline_data, ticker)
            logger.info(f"📐 [CZSC分析师] 转换完成: {len(bars)} 根 RawBar")

            # 3. 执行缠论核心分析（Rust 算法）
            czsc_obj = CZSC(bars)
            logger.info(
                f"📐 [CZSC分析师] 缠论分析完成: "
                f"分型={len(czsc_obj.fx_list)}, 笔={len(czsc_obj.bi_list)}"
            )

            # 4. 提取结构化信号
            signals = _extract_czsc_signals(czsc_obj)
            signals_json = json.dumps(signals, ensure_ascii=False)
            logger.info(f"📐 [CZSC分析师] 信号提取完成: trend={signals.get('trend')}, "
                       f"score={signals.get('trend_score')}, "
                       f"buy_signals={len(signals.get('buy_signals', []))}, "
                       f"sell_signals={len(signals.get('sell_signals', []))}")

            # 5. 用 LLM 生成可读报告
            report = _generate_czsc_report(llm, ticker, signals)

            # 6. 强制覆盖综合评分为脚本计算的 trend_score（LLM 报告保留，分数以脚本为准）
            score = signals.get("trend_score", 5)
            report = _override_score_in_report(report, score)
            logger.info(f"📐 [CZSC分析师] 综合评分已覆盖为脚本分: {score}/10")

            return {
                "czsc_report": report,
                "czsc_signals": signals_json,
            }

        except Exception as e:
            logger.error(f"❌ [CZSC分析师] 分析异常: {e}", exc_info=True)
            return {
                "czsc_report": f"缠论分析：计算过程中发生异常（{str(e)[:100]}），跳过缠论结构分析。",
                "czsc_signals": "{}",
            }

    return czsc_analyst_node
