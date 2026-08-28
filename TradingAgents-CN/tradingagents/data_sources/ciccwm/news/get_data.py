#!/usr/bin/env python3
"""
中金财富热门资讯查询工具
基于 EInformationTopicSecendPage 接口获取今日热榜和专题资讯。
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
from typing import Any, Dict, Optional


CONFIG_PATH = Path.home() / ".config" / "ciccwm" / "config.json"
API_URL = "https://skill.ciccwm.com/zzt/ext/fcgi/common.fcgi"
REPORT_URL = "https://webreport.ciccwm.com/zzt/fcgi/common.fcgi"
REQUEST_VERSION = "20260612"
REQUEST_TIMEOUT = 15
CMD_NAME = "SkillEInformationTopicSecendPage"
SKILL_NAME = "热榜资讯"
SKILL_UA_NAME = "ciccwm-hot-news-analysis"
PLATFORM_NAME = "standard"
REINSTALL_MESSAGE = (
    "未获取到有效的 CICCWM_API_KEY 或鉴权已失效。"
    "请前往 https://web.ciccwm.com/zzt/app/skills-center/#/ 重新安装 skills。"
)


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
    """创建兼容旧服务器的 HTTPS 请求上下文。"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers("ALL:@SECLEVEL=0")
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
    except Exception:
        pass
    return ctx


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


def build_payload(params: Dict[str, Any]) -> Dict[str, Any]:
    """构造 EInformationTopicSecendPage 请求体。"""
    return {
        "cmdname": CMD_NAME,
        "param": params,
    }


def query_hot_rank(
    page_num: int = 1,
    page_size: int = 10,
    news_type: Optional[int] = 1,
    raw: bool = False,
) -> Dict[str, Any]:
    """查询今日热榜。"""
    params = {
        "type": news_type if news_type is not None else 1,
        "page_num": page_num,
        "page_size": page_size,
        "scene": "1",
    }
    response = send_request(build_payload(params))
    if raw:
        return response

    return {
        "query": "hot_rank",
        "cmdname": CMD_NAME,
        "page_num": page_num,
        "page_size": page_size,
        "type": params["type"],
        "scene": "1",
        "data": _inject_redirect_url(response),
    }


def query_topic_info(
    spec_subject_id: Optional[int] = None,
    page_num: int = 1,
    page_size: int = 20,
    news_type: Optional[int] = 1,
    raw: bool = False,
) -> Dict[str, Any]:
    """查询专题资讯。"""
    params = {
        "type": news_type if news_type is not None else 1,
        "page_num": page_num,
        "page_size": page_size,
    }

    if spec_subject_id is not None:
        params["spec_subject_id"] = spec_subject_id

    response = send_request(build_payload(params))
    if raw:
        return response

    return {
        "query": "topic",
        "cmdname": CMD_NAME,
        "page_num": page_num,
        "page_size": page_size,
        "type": params["type"],
        "spec_subject_id": spec_subject_id,
        "data": _inject_redirect_url(response),
    }


def build_detail_url(params: Dict[str, Any], base_origin: str = "https://web.ciccwm.com") -> str:
    """
    根据热榜结构体参数拼接端外资讯详情页 URL。

    逻辑说明 (IS_APP=False):
    1. source_code == 'youyan-report' 且 detail_url 存在 → 直接返回 detail_url
    2. out_detail_url 存在 → 直接返回 out_detail_url
    3. 其他情况 → 拼接 /zzt/app/news/#/detail?msgNew=msgNew&id=... 仅简单字段

    Args:
        params: 热榜结构体字段字典
        base_origin: 站点 origin，默认 https://web.ciccwm.com

    Returns:
        拼接好的详情页 URL 字符串
    """
    source_code = params.get("source_code", "")
    detail_url = params.get("detail_url", "")
    out_detail_url = params.get("out_detail_url", "")
    item_id = params.get("id", "")

    if source_code == "youyan-report" and detail_url:
        return detail_url

    if out_detail_url:
        return out_detail_url

    from urllib.parse import quote

    base_url = f"{base_origin}/zzt/app/news/#/detail?msgNew=msgNew&id={item_id}"
    for key, value in params.items():
        if key != "id" and isinstance(value, (str, int, float)):
            base_url += f"&{key}={quote(str(value), safe='')}"

    return base_url


def _inject_redirect_url(data: Any) -> Any:
    """遍历接口返回数据，为列表中的每条记录注入 redirect_url 字段并移除 read_num。"""
    if isinstance(data, list):
        results = []
        for item in data:
            if isinstance(item, dict):
                processed = {**item, "redirect_url": build_detail_url(item)}
                processed.pop("read_num", None)
                results.append(processed)
            else:
                results.append(item)
        return results
    if isinstance(data, dict):
        return {k: _inject_redirect_url(v) for k, v in data.items()}
    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="中金财富热门资讯查询工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="查询类型")

    p_hot = subparsers.add_parser("hot_rank", help="查询今日热榜")
    p_hot.add_argument("--page_num", type=int, default=1, help="页码，默认1")
    p_hot.add_argument("--page_size", type=int, default=10, help="每页数量，默认10")
    p_hot.add_argument("--type", type=int, default=1, help="资讯类型，默认1")
    p_hot.add_argument("--raw", action="store_true", help="返回接口原始结构")

    p_topic = subparsers.add_parser("topic", help="查询专题资讯")
    p_topic.add_argument("--spec_subject_id", type=int, help="专题 id")
    p_topic.add_argument("--page_num", type=int, default=1, help="页码，默认1")
    p_topic.add_argument("--page_size", type=int, default=20, help="每页数量，默认20")
    p_topic.add_argument("--type", type=int, default=1, help="资讯类型，默认1")
    p_topic.add_argument("--raw", action="store_true", help="返回接口原始结构")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "hot_rank":
            result = query_hot_rank(
                page_num=args.page_num,
                page_size=args.page_size,
                news_type=args.type,
                raw=args.raw,
            )
        elif args.command == "topic":
            result = query_topic_info(
                spec_subject_id=args.spec_subject_id,
                page_num=args.page_num,
                page_size=args.page_size,
                news_type=args.type,
                raw=args.raw,
            )
        else:
            raise ValueError(f"不支持的查询类型: {args.command}")
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
