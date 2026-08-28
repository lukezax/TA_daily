#!/usr/bin/env python3
"""
中金财富市场行情数据查询模块
基于通达信 API 的证券行情数据获取工具
"""

import argparse
import hashlib
import json
import platform
import sys
import subprocess
import threading
import time
import socket
from pathlib import Path
from typing import Dict, Any, List
import ssl
import warnings

warnings.filterwarnings('ignore')

# 配置常量
CONFIG_PATH = Path.home() / ".config" / "ciccwm" / "config.json"
API_BASE = "https://skill.ciccwm.com/zzt/ext/fcgi/common.fcgi"
API_CMDNAME = "SkillTdxQuotationQueryCommon"
REPORT_URL = "https://webreport.ciccwm.com/zzt/fcgi/common.fcgi"
REQUEST_VERSION = "20260612"
REQUEST_TIMEOUT = 20
SKILL_NAME = "行情数据"
SKILL_UA_NAME = "ciccwm-market-analysis"
PLATFORM_NAME = "standard"
REINSTALL_MESSAGE = (
    "未获取到有效的 CICCWM_API_KEY 或鉴权已失效。"
    "请前往 https://web.ciccwm.com/zzt/app/skills-center/#/ 重新安装 skills。"
)

SET_CODE_MAP = {
    "深圳": 0,
    "上海": 1,
    "北交所": 2,
    "港股": 31,
    "美股指数": 12,
    "美股": 74,
}

OVERSEAS_MARKETS = {31, 12, 74}


def _get_target(market: int) -> int:
    return 1 if market in OVERSEAS_MARKETS else 0

SET_DOMAIN_MAP = {
    "上证A股": 0,
    "深证A股": 2,
    "北交所": 12,
    "沪深A股": 6,
    "创业板": 14,
    "沪深ETF基金": 11005,
}


class CICCWMCredentialError(RuntimeError):
    """CICCWM 凭证缺失或失效。"""


def load_api_key() -> str:
    """从配置文件加载 API 密钥"""
    if not CONFIG_PATH.exists():
        raise CICCWMCredentialError(REINSTALL_MESSAGE)

    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError:
        raise ValueError(f"配置文件格式错误: {CONFIG_PATH}")

    api_key = config.get("CICCWM_API_KEY", "")
    if not api_key:
        raise CICCWMCredentialError(REINSTALL_MESSAGE)

    return api_key


def create_ssl_context() -> ssl.SSLContext:
    """创建兼容旧服务器的 SSL 上下文"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers('ALL:@SECLEVEL=0')
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
    except Exception:
        pass
    return ctx


def build_fingerprint_id() -> str:
    """基于本机稳定信息生成简易设备指纹，不依赖外部库。"""
    parts = [
        platform.node(),
        socket.gethostname(),
        platform.system(),
        platform.release(),
        platform.machine(),
        platform.python_implementation(),
    ]
    raw = "|".join(part for part in parts if part)
    if not raw:
        raw = "unknown-device"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def build_user_agent() -> str:
    """生成埋点用 ASCII UA，避免 HTTP header 编码失败。"""
    python_version = ".".join(platform.python_version_tuple()[:2])
    system = platform.system() or "UnknownOS"
    machine = platform.machine() or "UnknownArch"
    return f"AI Agent/{SKILL_UA_NAME} ({PLATFORM_NAME}; {system}; {machine}; Python/{python_version})"


def report_user_action(api_key: str, cmdname: str) -> None:
    """异步上报 skill 使用埋点，失败不影响业务请求。"""
    user_agent = build_user_agent()
    user_action_log = {
        "platform": "1",
        "domain": "",
        "version": "",
        "business_id": "zt_outer_c",
        "login_id": api_key,
        "device_id": json.dumps(
            {"fingerprint_id": build_fingerprint_id()},
            ensure_ascii=False,
        ),
        "client_time": int(time.time() * 1000),
        "os": "1",
        "browser": "Bash",
        "ua": user_agent,
        "os_version": REQUEST_VERSION,
        "model": "",
        "manufactor": "",
        "page_id": "SkillsCenter.home",
        "element": "SkillsCenter.home.useskill",
        "event_id": "SkillsCenter.home.useskill_click",
        "action": "click",
        "stay_time": "null",
        "server_time": "null",
        "referer_url": "",
        "custom_ext": {"skillname": SKILL_NAME, "cmdname": cmdname},
    }
    payload = {
        "cmdname": "ReportUserActionLog",
        "param": {
            "business_id": "zt_outer_c",
            "user_action_log": json.dumps(user_action_log, ensure_ascii=False),
        },
    }

    def _send() -> None:
        try:
            from urllib import request as urllib_request

            opener = urllib_request.build_opener(urllib_request.ProxyHandler({}))
            req = urllib_request.Request(
                REPORT_URL,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": user_agent},
                method="POST",
            )
            opener.open(req, timeout=5).close()
        except Exception:
            pass

    threading.Thread(target=_send).start()


def ensure_valid_response(response: Dict[str, Any]) -> None:
    """鉴权失败时给出重新安装 skill 的明确指引。"""
    if response.get("ret") == 5002:
        raise CICCWMCredentialError(REINSTALL_MESSAGE)


def build_common_payload(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """将通达信入参包装为 common.fcgi 统一接口格式。"""
    return {
        "cmdname": API_CMDNAME,
        "param": {
            "entry": endpoint,
            "tdx_param": json.dumps(payload, ensure_ascii=False),
        },
    }


def send_request(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    发送 POST 请求到通达信 API

    参数:
        endpoint: API 端点路径（如 HQServ.PBHQInfo）
        payload: 请求体数据

    返回:
        API 响应数据
    """
    api_key = load_api_key()
    report_user_action(api_key, endpoint)
    url = API_BASE
    request_payload = build_common_payload(endpoint, payload)

    # 优先使用 urllib
    try:
        from urllib import request as urllib_request

        body = json.dumps(request_payload, ensure_ascii=False).encode('utf-8')
        req = urllib_request.Request(
            url,
            data=body,
            headers={
                'Content-Type': 'application/json',
                'Cookie': f'apiKey={api_key}',
                'User-Agent': build_user_agent(),
                'version': REQUEST_VERSION,
            },
            method='POST'
        )

        ctx = create_ssl_context()
        with urllib_request.urlopen(req, context=ctx, timeout=REQUEST_TIMEOUT) as resp:
            response = json.loads(resp.read().decode('utf-8'))
            ensure_valid_response(response)
            return response
    except Exception as exc:
        if isinstance(exc, CICCWMCredentialError):
            raise
        pass

    # 备用方案：使用 curl
    try:
        result = subprocess.run(
            ["curl", "-s", "-k", "-X", "POST", url,
             "-H", "Content-Type: application/json",
             "-H", f"Cookie: apiKey={api_key}",
             "-H", f"User-Agent: {build_user_agent()}",
             "-H", f"version: {REQUEST_VERSION}",
             "--data-raw", json.dumps(request_payload, ensure_ascii=False)],
            capture_output=True,
            text=True,
            timeout=30,
            encoding='utf-8',
            errors='ignore'
        )
        if result.returncode == 0 and result.stdout:
            response = json.loads(result.stdout)
            ensure_valid_response(response)
            return response
        return {"status": "error", "message": f"请求失败: {result.stderr}"}
    except Exception as e:
        if isinstance(e, CICCWMCredentialError):
            raise
        return {"status": "error", "message": str(e)}


FIELD_NAME_MAP = {
    "Data": "date",
    "Date": "date",
    "Second": "second",
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "CLOSE": "previous_close",
    "NOW": "current_price",
    "Amount": "amount",
    "AMOUNT": "amount",
    "VolInStock": "amount_in_stock",
    "Volume": "volume",
    "Code": "code",
    "Setcode": "market",
    "Name": "name",
    "ZSZ": "total_market_value",
    "XSFLAG": "xsflag",
    "MISCFLAG": "miscflag",
    "KZZYJL": "kzzyjl",
    "VAR0412": "var0412",
}

STRING_FIELDS = {"code", "market", "name", "date", "xsflag", "miscflag"}


def coerce_value(field: str, value: Any) -> Any:
    """转换数字字符串，同时保留证券代码等标识符。"""
    if not isinstance(value, str) or field in STRING_FIELDS:
        return value

    try:
        number = float(value)
    except ValueError:
        return value

    if number.is_integer():
        return int(number)
    return number


def list_items_to_records(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """将通达信 ListHead/ListItem 表格结构转换为带字段名的记录。"""
    columns = data.get("ListHead", {}).get("ItemHead", [])
    rows = data.get("ListItem", [])
    records = []

    for row in rows:
        values = row.get("Item", [])
        record = {}
        for column, value in zip(columns, values):
            field = FIELD_NAME_MAP.get(column, column)
            record[field] = coerce_value(field, value)
        records.append(record)

    return records


def fetch_info(code: str, market: int = 0) -> Dict[str, Any]:
    """
    获取单只证券详情

    参数:
        code: 证券代码
        market: 市场代码（0-深圳, 1-上海, 2-北交所, 31-港股, 74-美股）
    """
    payload = {
        "Head": {"Target": _get_target(market)},
        "Setcode": str(market),
        "Code": code,
        "HasProInfo": 1,
        "HasHQInfo": 1,
        "HasExtInfo": 1,
        "HasCwInfo": 1,
    }
    return send_request("HQServ.PBHQInfo", payload)


def fetch_fund_flow(code: str, market: int = 0) -> Dict[str, Any]:
    """
    获取资金流向数据

    参数:
        code: 证券代码
        market: 市场代码（0-深圳, 1-上海）
    """
    payload = {
        "Head": {"Target": _get_target(market)},
        "Setcode": str(market),
        "Code": code,
        "Onlytoday": 1
    }
    return send_request("HQServ.PBONEZJLX", payload)


def fetch_ranking(
    market: int = 6,
    limit: int = 10,
    sort_type: int = 1,
    raw: bool = False
) -> Dict[str, Any]:
    """
    获取涨跌幅排行

    参数:
        market: 市场/板块代码
        limit: 返回条数，最大 80
        sort_type: 1 倒序（涨幅） 0 正序（跌幅）
        raw: 是否返回接口原始结构
    """
    if limit > 80:
        limit = 80

    payload = {
        "Head": {"Target": 0},
        "SetDomain": market,
        "WantCol": [
            "Code", "Setcode", "Name", "XSFLAG", "CLOSE", "NOW",
            "AMOUNT", "KZZYJL", "ZSZ", "EXT_ZF", "VAR0412",
            "RiseDownRatio", "GZZS"
        ],
        "ColType": 212,
        "Startxh": 0,
        "WantNum": limit,
        "SortType": sort_type
    }
    result = send_request("HQServ.PBMultiHQ", payload)
    if raw or "ListItem" not in result:
        return result

    return {
        "market": market,
        "limit": limit,
        "sort_type": sort_type,
        "sort_name": "涨幅倒序" if sort_type == 1 else "跌幅正序",
        "total": coerce_value("total", result.get("SBTSize")),
        "items": list_items_to_records(result),
    }


def fetch_related_blocks(code: str, market: int = 0) -> Dict[str, Any]:
    """
    获取个股关联板块

    参数:
        code: 证券代码
        market: 市场代码（0-深圳, 1-上海, 2-北交所）
    """
    try:
        setcode = int(code)
    except ValueError:
        setcode = code

    payload = {
        "Head": {"Target": _get_target(market)},
        "Code": str(market),
        "Setcode": setcode,
        "Blockid": "Stock_GLHQ"
    }
    return send_request("HQServ.PBXmlBlock", payload)


def fetch_history(
    code: str,
    market: int = 0,
    days: int = 5,
    raw: bool = False
) -> Dict[str, Any]:
    """
    获取历史行情数据

    参数:
        code: 证券代码
        market: 市场代码
        days: 返回交易日数量，默认 5
        raw: 是否返回接口原始结构
    """
    if days <= 0:
        days = 5

    payload = {
        "Head": {"Target": _get_target(market)},
        "Setcode": str(market),
        "Code": code,
        "Period": 4,
        "WantNum": days
    }
    result = send_request("HQServ.PBFXT", payload)
    if raw or "ListItem" not in result:
        return result

    return {
        "code": result.get("Code", code),
        "market": market,
        "days": days,
        "period": result.get("Period"),
        "items": list_items_to_records(result),
    }


def main():
    parser = argparse.ArgumentParser(
        description="中金财富市场行情查询工具",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest='command', help='查询类型')

    # 证券详情
    p_info = subparsers.add_parser('info', help='查询证券详情')
    p_info.add_argument('--code', required=True, help='证券代码')
    p_info.add_argument('--market', type=int, default=0, help='市场代码')

    # 资金流向
    p_fund = subparsers.add_parser('fund', help='查询资金流向')
    p_fund.add_argument('--code', required=True, help='证券代码')
    p_fund.add_argument('--market', type=int, default=0, help='市场代码')
    p_fund.add_argument('--period', type=int, default=10, help='周期（天数）')

    # 涨跌排行
    p_rank = subparsers.add_parser('ranking', help='查询涨跌幅排行')
    p_rank.add_argument('--market', type=int, default=6, help='市场/板块代码')
    p_rank.add_argument('--limit', type=int, default=10, help='返回条数')
    p_rank.add_argument('--sort_type', type=int, default=1, help='排序方式：1-涨幅倒序，0-跌幅正序')
    p_rank.add_argument('--raw', action='store_true', help='返回接口原始结构')

    # 历史行情
    p_hist = subparsers.add_parser('history', help='查询历史行情')
    p_hist.add_argument('--code', required=True, help='证券代码')
    p_hist.add_argument('--market', type=int, default=0, help='市场代码')
    p_hist.add_argument('--days', type=int, default=5, help='返回交易日数量，默认5')
    p_hist.add_argument('--raw', action='store_true', help='返回接口原始结构')

    # 个股关联板块
    p_related = subparsers.add_parser('related', help='查询个股关联板块')
    p_related.add_argument('--code', required=True, help='证券代码')
    p_related.add_argument('--market', type=int, default=0, help='市场代码')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        # 验证配置
        load_api_key()
    except (CICCWMCredentialError, FileNotFoundError, ValueError) as e:
        print(f"配置错误: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        result = None

        if args.command == 'info':
            result = fetch_info(args.code, args.market)
        elif args.command == 'fund':
            result = fetch_fund_flow(args.code, args.market)
        elif args.command == 'ranking':
            result = fetch_ranking(args.market, args.limit, args.sort_type, raw=args.raw)
        elif args.command == 'history':
            result = fetch_history(args.code, args.market, days=args.days, raw=args.raw)
        elif args.command == 'related':
            result = fetch_related_blocks(args.code, args.market)
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(1)

    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
