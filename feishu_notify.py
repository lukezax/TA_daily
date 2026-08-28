"""
飞书自定义机器人通知模块
- 签名算法：timestamp + "\n" + secret -> HMAC-SHA256 -> Base64
- 消息类型：interactive 卡片，column_set 多列布局，每只股票一个分组
"""
import hashlib
import hmac
import base64
import json
import os
import time
import datetime
import requests

try:
    from pipeline.report_scores import format_winrate, load_scores
except ImportError:
    # 独立运行时（如 dist 打包目录）无 pipeline 包，退化读取逻辑置于下方
    format_winrate = None
    load_scores = None

FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/53981380-b6ac-4b8f-9e9e-44e76e738c8e"
FEISHU_SECRET = "aYvDtPCjQjPocmbU2vpWkg"
STOCK_URL_TEMPLATE = "https://stockpage.10jqka.com.cn/{code}/"

# TradingAgents 结果目录（可通过环境变量覆盖）
TA_RESULTS_DIR = os.getenv(
    "PIPELINE_TA_RESULTS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "TradingAgents-CN", "results")
)


def _gen_sign(secret: str, timestamp: int) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def _post(payload: dict) -> bool:
    timestamp = int(time.time())
    sign = _gen_sign(FEISHU_SECRET, timestamp)
    payload["timestamp"] = str(timestamp)
    payload["sign"] = sign
    size_kb = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) / 1024
    print(f"[飞书] 发送中，消息大小 {size_kb:.1f}KB ...")
    try:
        resp = requests.post(FEISHU_WEBHOOK, json=payload, timeout=8)
        print(f"[飞书] HTTP {resp.status_code}")
        result = resp.json()
        print(f"[飞书] 返回: {result}")
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            print("[飞书] 发送成功")
            return True
        print(f"[飞书] 发送失败: {result}")
        return False
    except requests.exceptions.Timeout:
        print("[飞书] 超时（8s），跳过")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"[飞书] 连接失败: {e}")
        return False
    except Exception as e:
        print(f"[飞书] 异常: {type(e).__name__}: {e}")
        return False


def send_feishu_text(text: str) -> bool:
    return _post({"msg_type": "text", "content": {"text": text}})


def _fmt(val, decimals=2, suffix=""):
    if val is None or val == "":
        return "—"
    try:
        return f"{float(val):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return str(val)


def _bool_icon(val):
    m = {True: "✅", False: "❌", "True": "✅", "False": "❌"}
    return m.get(val, "—")


def _md(content: str, align: str = "left") -> dict:
    """markdown element"""
    return {"tag": "markdown", "content": content, "text_align": align}


def _col(elements: list, weight: int = 1) -> dict:
    """column element"""
    return {
        "tag": "column",
        "width": "weighted",
        "weight": weight,
        "vertical_align": "top",
        "vertical_spacing": "8px",
        "elements": elements,
    }


def _col_set(columns: list, bg: str = "default", flex_mode: str = "") -> dict:
    """column_set element"""
    result = {
        "tag": "column_set",
        "background_style": bg,
        "horizontal_spacing": "8px",
        "horizontal_align": "left",
        "columns": columns,
    }
    if flex_mode:
        result["flex_mode"] = flex_mode
    return result


def _divider() -> dict:
    return {"tag": "hr"}


def _load_stock_scores(stock_code: str, date_str: str) -> dict:
    """
    从报告文件读取缠论评分与养家赢面。
    date_str 下无报告时回退到该股票最晚日期目录。
    独立运行（无 pipeline 包）时返回空 dict。
    """
    if load_scores is None:
        return {}

    code = stock_code.split(".")[0]
    base_dir = os.path.join(TA_RESULTS_DIR, code)

    # 优先使用指定日期
    scores = load_scores(TA_RESULTS_DIR, stock_code, date_str)
    if scores.get("chan_score") is not None or scores.get("yangjia_winrate"):
        return scores

    # 回退：找该股票最晚有报告目录的日期
    try:
        if os.path.isdir(base_dir):
            date_dirs = sorted(
                (d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))),
                reverse=True,
            )
            for d in date_dirs:
                scores = load_scores(TA_RESULTS_DIR, stock_code, d)
                if scores.get("chan_score") is not None or scores.get("yangjia_winrate"):
                    return scores
    except OSError:
        pass

    return {}


def _score_color(kind: str, score) -> str:
    """按阈值给分数上色：缠≥8绿/5-7橙/≤4红；赢面高值>70绿/60-70橙/<60红"""
    if score is None:
        return "grey"
    if kind == "chan":
        if score >= 8:
            return "green"
        if score >= 5:
            return "orange"
        return "red"
    # kind == "win"
    if score > 70:
        return "green"
    if score >= 60:
        return "orange"
    return "red"


def _stock_elements(r: dict) -> list:
    """
    将单只股票转为卡片 elements 列表
    布局：
      行1：代码+名称（超链接）| 交易所 | 得分
      行2（表头灰底）：行情 | 市值 | 指标
      行3（数据）：价格数据 | 市值数据 | KDJ数据
      行4（表头灰底）：B1条件 | 评分条件
      行5（数据）：11个条件 | 4个评分条件
      行6（表头灰底）：回测/斜率 | 形态
      行7（数据）：回测数据 | 形态数据
      分隔线
    """
    stock = r["stock"]
    d = r.get("details", {})
    pure_code = stock["code"].split(".")[0]
    url = STOCK_URL_TEMPLATE.format(code=pure_code)

    def v(key, dec=2, suf=""):
        return _fmt(d.get(key), dec, suf)

    def b(key):
        return _bool_icon(d.get(key))

    open_v = _fmt(d.get("开盘价") or d.get("open"))
    high_v = _fmt(d.get("最高价") or d.get("high"))
    low_v  = _fmt(d.get("最低价") or d.get("low"))
    total_cap = _fmt(float(d.get("总市值") or 0) / 1e8, 1, "亿")
    circ_cap  = _fmt(float(d.get("流通市值") or 0) / 1e8, 1, "亿")
    vol_v     = _fmt(d.get("volume") or d.get("成交量"), 0)

    score = d.get("新增条件总分", "—")
    score_color = "green" if score == 4 else ("orange" if score == 3 else "red")

    elements = []

    # ── 股票标题行 ────────────────────────────────────────────────────────
    elements.append(_col_set([
        _col([_md(f"**[{stock['code']} {stock['name']}]({url})**")], weight=3),
        _col([_md(f"{stock['exchange']}", "center")], weight=1),
        _col([_md(f"<font color='{score_color}'>**得分 {score}/4**</font>", "center")], weight=1),
    ]))

    # ── 缠论评分 + 养家赢面 行（由 send_b1_results 预计算写入 r["scores"]）──
    scores = r.get("scores", {}) or {}
    chan = scores.get("chan_score")
    win = scores.get("yangjia_winrate")
    win_str = scores.get("yangjia_winrate_str")
    chan_txt = f"**{chan}/10**" if chan is not None else "—"
    win_txt = f"**{win_str}**" if win_str else "—"
    elements.append(_col_set([
        _col([_md(
            f"🧠 缠论：<font color='{_score_color('chan', chan)}'>{chan_txt}</font>"
        )]),
        _col([_md(
            f"🎯 赢面：<font color='{_score_color('win', win.get('high') if win else None)}'>{win_txt}</font>"
        )]),
    ]))

    # ── 行情 + 市值 + 指标 表头 ───────────────────────────────────────────
    elements.append(_col_set([
        _col([_md("**行情**", "center")]),
        _col([_md("**市值/量**", "center")]),
        _col([_md("**KDJ/均线**", "center")]),
    ], bg="grey"))

    # ── 行情 + 市值 + 指标 数据 ───────────────────────────────────────────
    elements.append(_col_set([
        _col([_md(
            f"收盘：**{v('收盘价')}**\n"
            f"开盘：{open_v}  最高：{high_v}\n"
            f"最低：{low_v}\n"
            f"涨幅：**{v('涨幅')}%**  振幅：{v('振幅')}%"
        )]),
        _col([_md(
            f"总市值：{total_cap}\n"
            f"流通：{circ_cap}\n"
            f"成交量：{vol_v}"
        )]),
        _col([_md(
            f"J：**{v('J')}**  K：{v('K')}  D：{v('D')}\n"
            f"MA60：{v('MA60')}\n"
            f"白线：{v('白线')}  黄线：{v('黄线')}\n"
            f"前日收：{v('n-1日收盘价')}  黄距：{v('到黄线距离')}\n"
            f"前周收：{v('n-1周收盘价')}  周白：{v('周K白线')}"
        )]),
    ]))

    # ── B1条件 + 评分条件 表头 ────────────────────────────────────────────
    elements.append(_col_set([
        _col([_md("**B1原始条件**", "center")]),
        _col([_md("**评分条件**", "center")]),
    ], bg="grey"))

    # ── B1条件 + 评分条件 数据 ────────────────────────────────────────────
    elements.append(_col_set([
        _col([_md(
            f"J<13：{b('J<13')}  >MA60：{b('收盘价>MA60')}  >ZXDKX：{b('收盘价>ZXDKX')}\n"
            f"Q>KX：{b('ZXDQ>ZXDKX')}  振<7：{b('振幅<7')}\n"
            f"涨>=-2：{b('涨幅>=-2')}  涨<2：{b('涨幅<2')}\n"
            f"倍量：{b('倍量柱条件')}  市值：{b('市值条件')}\n"
            f"黄白间：{b('n-1日K在黄白值之间')}  周>白：{b('n-1周K高于白线')}"
        )]),
        _col([_md(
            f"30日倍量：{b('新增条件1_30日内倍量')}（{v('30日倍量次数', 0)}次）\n"
            f"无大卖：{b('新增条件2_120日内无大量卖出')}（违{v('120日大量卖出次数', 0)}次）\n"
            f"涨幅控：{b('新增条件3_30日内涨幅控制')}\n"
            f"换手控：{b('新增条件4_30日内换手率控制')}"
        )]),
    ]))

    # ── 回测/斜率 + 形态 表头 ─────────────────────────────────────────────
    elements.append(_col_set([
        _col([_md("**回测 / 斜率**", "center")]),
        _col([_md("**形态统计**", "center")]),
    ], bg="grey"))

    # ── 回测/斜率 + 形态 数据 ─────────────────────────────────────────────
    elements.append(_col_set([
        _col([_md(
            f"5天回测：**{v('5天回测收益率')}%**（前价：{v('5天前价格')}）\n"
            f"3天斜率：{v('日K3天斜率')}  <0.2：{b('日K3天斜率<0.2')}\n"
            f"gap%：{v('黄白gap占股价%')}  >5%：{b('黄白gap>5%')}\n"
            f"30日斜：{v('30日K斜率')}  120周斜：{v('120周K斜率')}"
        )]),
        _col([_md(
            f"30天涨幅：{v('30天涨幅')}%（限{v('30天涨幅限制', 0)}）达标：{b('30天涨幅达标')}\n"
            f"无连涨停：{b('30天无连续涨停')}  无长上影：{b('无长上影')}\n"
            f"无风车：{b('无顶部大风车')}  无异量：{b('无非正常放量')}\n"
            f"无跳空：{b('无跳空')}"
        )]),
    ]))

    elements.append(_divider())
    return elements


def _build_card(batch: list, date_str: str, total: int,
                batch_num: int, total_batches: int) -> dict:
    title = f"📊 B1筛选结果 · {date_str}  共{total}只"
    if total_batches > 1:
        title += f"（第{batch_num}/{total_batches}批）"

    elements = [_md(f"**{title}**")]
    for r in batch:
        elements.extend(_stock_elements(r))

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"update_multi": True},
            "i18n_elements": {
                "zh_cn": elements,
            },
            "i18n_header": {},
        },
    }


def _split_into_batches(qualified_results: list, date_str: str) -> list:
    """动态分批，确保每条消息不超过 19KB"""
    MAX_BYTES = 19 * 1024
    total = len(qualified_results)
    batches = []
    i = 0
    while i < total:
        lo, hi = 1, min(30, total - i)
        best = 1
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = qualified_results[i:i + mid]
            msg = _build_card(candidate, date_str, total, len(batches) + 1, 1)
            size = len(json.dumps(msg, ensure_ascii=False).encode("utf-8"))
            if size <= MAX_BYTES:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        batches.append(qualified_results[i:i + best])
        i += best
    return batches


def send_b1_results(qualified_results: list) -> None:
    """
    将B1筛选符合条件的股票以 interactive 卡片形式发送到飞书
    每只股票多行分组展示，代码为超链接，动态分批不超 20KB
    """
    if not qualified_results:
        send_feishu_text("【B1筛选完成】今日无符合条件的股票。")
        return

    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    report_date = date_str[:10]
    total = len(qualified_results)

    # 预计算每只股票的缠论评分/养家赢面（避免分批二分时重复读文件）
    for r in qualified_results:
        scores = _load_stock_scores(r["stock"]["code"], report_date)
        if scores.get("yangjia_winrate"):
            scores["yangjia_winrate_str"] = format_winrate(scores["yangjia_winrate"]) if format_winrate else "—"
        r["scores"] = scores

    batches = _split_into_batches(qualified_results, date_str)
    total_batches = len(batches)
    print(f"[飞书] 共 {total} 只股票，分 {total_batches} 批发送")

    # 先发分割线，区分每次筛选结果
    sep = f"{'━' * 12} 🔔 B1筛选 {date_str} 共{total}只 {'━' * 12}"
    send_feishu_text(sep)
    time.sleep(0.3)
    send_feishu_text(sep)
    time.sleep(0.3)
    send_feishu_text(sep)
    time.sleep(0.3)
    send_feishu_text(sep)
    time.sleep(0.3)
    send_feishu_text(sep)
    time.sleep(0.3)

    for idx, batch in enumerate(batches):
        batch_num = idx + 1
        print(f"[飞书] 发送第 {batch_num}/{total_batches} 批，{len(batch)} 只")
        msg = _build_card(batch, date_str, total, batch_num, total_batches)
        ok = _post(msg)
        if not ok:
            print(f"[飞书] 第 {batch_num} 批失败，继续")
        if batch_num < total_batches:
            time.sleep(0.3)
