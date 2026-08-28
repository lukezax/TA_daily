#!/usr/bin/env python3
"""
中金财富股票财务数据查询工具
基于 EQuoteZhongzhuoF10Common 接口获取主要指标、利润表、现金流量表、资产负债表。
"""

import argparse
import hashlib
import json
import platform
import ssl
import sys
import threading
import time
import socket
from pathlib import Path
from typing import Any, Dict, List


CONFIG_PATH = Path.home() / ".config" / "ciccwm" / "config.json"
API_URL = "https://skill.ciccwm.com/zzt/ext/fcgi/common.fcgi"
REPORT_URL = "https://webreport.ciccwm.com/zzt/fcgi/common.fcgi"
REQUEST_VERSION = "20260612"
REQUEST_TIMEOUT = 20
SKILL_NAME = "财务分析"
SKILL_UA_NAME = "ciccwm-stock-finance-analysis"
PLATFORM_NAME = "standard"
CMD_NAME = "SkillEQuoteZhongzhuoF10Common"
REINSTALL_MESSAGE = (
    "未获取到有效的 CICCWM_API_KEY 或鉴权已失效。"
    "请前往 https://web.ciccwm.com/zzt/app/skills-center/#/ 重新安装 skills。"
)

ACTION_MAP = {
    "indicators": "48571",
    "income": "48572",
    "cashflow": "48573",
    "balance": "48574",
}

STATEMENT_NAME_MAP = {
    "indicators": "主要指标",
    "income": "利润表",
    "cashflow": "现金流量表",
    "balance": "资产负债表",
}

QTIME_MAP = {
    "annual": "12",
    "mid": "06",
    "q1": "03",
    "q3": "09",
    "12": "12",
    "06": "06",
    "03": "03",
    "09": "09",
}


class CICCWMCredentialError(RuntimeError):
    """CICCWM 凭证缺失或失效。"""


def load_api_key() -> str:
    """从配置文件加载中金财富 API 密钥。"""
    if not CONFIG_PATH.exists():
        raise CICCWMCredentialError(REINSTALL_MESSAGE)

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as file:
            config = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件格式错误: {CONFIG_PATH}") from exc

    api_key = config.get("CICCWM_API_KEY", "")
    if not api_key:
        raise CICCWMCredentialError(REINSTALL_MESSAGE)

    return api_key


def create_ssl_context() -> ssl.SSLContext:
    """创建 HTTPS 请求上下文。"""
    ctx = ssl.create_default_context()
    return ctx


def build_payload(action: str, code: str, qtime: str = "12", gtype: str = "0") -> Dict[str, Any]:
    """构造 EQuoteZhongzhuoF10Common 请求体。"""
    req_json = {
        "action": action,
        "gpcode": code,
        "qtime": qtime,
        "gtype": gtype,
    }
    return {
        "cmdname": CMD_NAME,
        "param": {
            "req_json": json.dumps(req_json, ensure_ascii=False)
        }
    }


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


def send_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    """发送请求并返回接口原始 JSON。"""
    api_key = load_api_key()
    report_user_action(api_key, payload.get("cmdname", CMD_NAME))
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "Cookie": "apiKey=" + api_key,
        "User-Agent": build_user_agent(),
        "version": REQUEST_VERSION,
    }

    try:
        from urllib import request as urllib_request

        req = urllib_request.Request(
            API_URL,
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=REQUEST_TIMEOUT, context=create_ssl_context()) as resp:
            response = json.loads(resp.read().decode("utf-8"))
            ensure_valid_response(response)
            return response
    except Exception as exc:
        if isinstance(exc, CICCWMCredentialError):
            raise
        return {"status": "error", "message": f"请求失败: {exc}"}


def parse_rsp_json(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """解析接口包装层中的 rsp.rsp_json 字符串。"""
    if response.get("ret") != 0:
        raise ValueError(response.get("msg") or "接口返回 ret 非 0")

    rsp = response.get("rsp", {})
    if rsp.get("ret_code") != 0:
        raise ValueError(rsp.get("ret_msg") or "接口返回 ret_code 非 0")

    rsp_json = rsp.get("rsp_json", "[]")
    if not rsp_json:
        return []

    parsed = json.loads(rsp_json)
    if not isinstance(parsed, list):
        raise ValueError("rsp_json 不是数组结构")
    return parsed


def apply_limit(items: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """按期数限制返回记录；limit 为 0 时返回全部。"""
    if limit == 0:
        return items
    if limit < 0:
        limit = 5
    return items[:limit]


def query_finance(
    statement: str,
    code: str,
    qtime: str = "12",
    gtype: str = "0",
    limit: int = 5,
    raw: bool = False,
) -> Dict[str, Any]:
    """查询股票财务数据。"""
    if statement not in ACTION_MAP:
        raise ValueError(f"不支持的报表类型: {statement}")

    normalized_qtime = QTIME_MAP.get(qtime, qtime)
    payload = build_payload(ACTION_MAP[statement], code, normalized_qtime, gtype)
    response = send_request(payload)
    if raw:
        return response

    items = parse_rsp_json(response)
    limited_items = apply_limit(items, limit)
    return {
        "code": code,
        "statement": statement,
        "statement_name": STATEMENT_NAME_MAP[statement],
        "action": ACTION_MAP[statement],
        "qtime": normalized_qtime,
        "gtype": gtype,
        "limit": limit,
        "total": len(items),
        "items": limited_items,
    }


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """添加各报表命令的通用参数。"""
    parser.add_argument("--code", required=True, help="证券代码，如 600519")
    parser.add_argument(
        "--qtime",
        default="12",
        help="报表类型：12/annual 年报，06/mid 中报，03/q1 一季报，09/q3 三季报",
    )
    parser.add_argument("--gtype", default="0", help="页面类型，默认0；单季度查询传1")
    parser.add_argument("--limit", type=int, default=5, help="返回期数，默认5；0表示全部")
    parser.add_argument("--raw", action="store_true", help="返回接口原始结构")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="中金财富股票财务数据查询工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="查询类型")

    for command, help_text in [
        ("indicators", "查询财务主要指标"),
        ("income", "查询利润表"),
        ("cashflow", "查询现金流量表"),
        ("balance", "查询资产负债表"),
    ]:
        sub = subparsers.add_parser(command, help=help_text)
        add_common_args(sub)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        result = query_finance(
            args.command,
            args.code,
            qtime=args.qtime,
            gtype=args.gtype,
            limit=args.limit,
            raw=args.raw,
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
