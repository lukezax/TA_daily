"""
智兔 API 数据源适配器
基于 https://api.zhituapi.com 提供股票列表、实时行情、历史K线数据
"""
import os
import logging
import time
from typing import Optional, Dict, List
from datetime import datetime, timedelta

import pandas as pd
import requests
import urllib3

# 智兔 API 后端部分服务器 SSL 证书域名不匹配，禁用验证避免间歇性 SSLError
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from .base import DataSourceAdapter

logger = logging.getLogger(__name__)


class ZhituAdapter(DataSourceAdapter):
    """智兔 API 数据源适配器（支持多 token 轮换）"""

    # 免费 token 列表（每天 200 次限制），优先使用
    FREE_TOKENS = [
        "74DCAD17-3EC8-45D7-857D-A747D9CF5FDD",
        "559603A5-7824-4626-9BEC-2DDDC520DAD4",
        "7DF40DE4-14E7-45B9-BFBB-8543D32FCFC1",
        "B4E0D8B4-A247-4585-8321-ACCF1F038BD4",
    ]
    FREE_TOKEN_DAILY_LIMIT = 198  # 每个免费 token 每天最多 198 次（留 2 次余量）

    def __init__(self):
        super().__init__()
        self.base_url = "https://api.zhituapi.com"
        # 付费 token（兜底）
        self._paid_token = os.getenv("ZHITU_API_TOKEN", "")
        self.request_interval = 0.5  # 请求间隔（秒）

        # token 使用计数（按日期重置）
        self._token_usage = {}  # {token: count}
        self._usage_date = ""   # 当前计数对应的日期

    @property
    def token(self) -> str:
        """获取当前可用的 token（优先免费 token，用完后切换到付费 token）"""
        from datetime import date
        today = date.today().isoformat()

        # 日期变更时重置计数
        if self._usage_date != today:
            self._token_usage = {}
            self._usage_date = today

        # 优先使用免费 token
        for free_token in self.FREE_TOKENS:
            usage = self._token_usage.get(free_token, 0)
            if usage < self.FREE_TOKEN_DAILY_LIMIT:
                return free_token

        # 免费 token 全部用完，使用付费 token
        return self._paid_token

    def _record_token_usage(self, token: str):
        """记录 token 使用次数"""
        self._token_usage[token] = self._token_usage.get(token, 0) + 1

    @property
    def name(self) -> str:
        return "zhitu"

    def _get_default_priority(self) -> int:
        return 1  # 兜底优先级（免费数据源优先，zhitu作为最后防线）

    def is_available(self) -> bool:
        """检查智兔 API 是否可用（至少有一个 token 可用）"""
        return bool(self.token and self.token.strip())

    def _safe_float(self, value) -> Optional[float]:
        """安全转换为浮点数"""
        try:
            if value is None or value == '' or value == 'None':
                return None
            return float(value)
        except (ValueError, TypeError):
            return None

    def _request(self, url: str, timeout: int = 10) -> Optional[dict]:
        """
        发送 HTTP 请求，带重试和 token 故障转移。

        逻辑：
        1. 用当前 token 请求
        2. 如果失败（网络/超时/HTTP错误），标记当前 token 为耗尽，切换下一个 token 重试
        3. 所有 token（免费+付费）都失败 → 返回 None
        """
        import re

        max_attempts = len(self.FREE_TOKENS) + 2  # 免费 tokens + 付费 token + 1次额外重试

        for attempt in range(max_attempts):
            current_token = self.token
            if not current_token:
                logger.error("智兔 API: 无可用 token")
                return None

            # 替换 URL 中的 token
            if 'token=' in url:
                actual_url = re.sub(r'token=[^&]+', f'token={current_token}', url)
            else:
                actual_url = url

            # 打印完整的请求 URL，方便调试
            logger.info(f"智兔 API 请求: {actual_url}")

            try:
                resp = requests.get(actual_url, timeout=timeout, verify=False,
                                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
                resp.raise_for_status()
                data = resp.json()

                # 打印响应摘要，方便调试
                if isinstance(data, dict):
                    logger.info(f"智兔 API 响应: code={data.get('code')}, error={data.get('error')}, keys={list(data.keys())[:5]}")
                elif isinstance(data, list):
                    logger.info(f"智兔 API 响应: list length={len(data)}")
                else:
                    logger.info(f"智兔 API 响应: type={type(data)}")

                # 检查 API 层面的错误（如 token 无效/过期）
                if isinstance(data, dict) and data.get('error'):
                    error_msg = str(data.get('error', ''))
                    logger.warning(f"智兔 API 返回错误: {error_msg} (token: {current_token[:8]}...)")
                    # 标记当前 token 为耗尽，尝试下一个
                    self._token_usage[current_token] = self.FREE_TOKEN_DAILY_LIMIT + 1
                    continue

                # 请求成功
                self._record_token_usage(current_token)
                return data

            except requests.exceptions.Timeout:
                logger.warning(f"智兔 API 请求超时 (token: {current_token[:8]}..., 第{attempt+1}次)")
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"智兔 API 连接失败: {e} (token: {current_token[:8]}..., 第{attempt+1}次)")
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response else 0
                logger.warning(f"智兔 API HTTP {status_code} (token: {current_token[:8]}..., 第{attempt+1}次)")
                if status_code in (401, 403):
                    # token 无效/过期，标记为耗尽
                    self._token_usage[current_token] = self.FREE_TOKEN_DAILY_LIMIT + 1
            except Exception as e:
                logger.error(f"智兔 API 请求异常: {e} (token: {current_token[:8]}..., 第{attempt+1}次)")

            # 当前 token 失败，标记为耗尽以便切换到下一个
            self._token_usage[current_token] = self._token_usage.get(current_token, 0) + self.FREE_TOKEN_DAILY_LIMIT
            time.sleep(self.request_interval)

        # 所有 token 都失败
        logger.error("智兔 API: 所有 token 均请求失败，放弃")
        return None

    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """
        获取沪深A股股票列表
        GET /hs/list/all?token={token}
        返回 DataFrame(symbol, name, ts_code, market)
        """
        if not self.is_available():
            return None

        try:
            url = f"{self.base_url}/hs/list/all?token={self.token}"
            data = self._request(url, timeout=15)
            if data is None:
                return None

            # 处理不同的响应结构
            stocks_raw = []
            if isinstance(data, list):
                stocks_raw = data
            elif isinstance(data, dict):
                if data.get("code") == 200 and data.get("data"):
                    stocks_raw = data["data"]
                elif isinstance(data.get("data"), list):
                    stocks_raw = data["data"]

            if not stocks_raw:
                logger.warning("智兔 API: get_stock_list 返回空数据")
                return None

            # 转换为 DataFrame
            records = []
            for item in stocks_raw:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("dm", "")).zfill(6)
                name = item.get("mc", "")
                exchange = item.get("jys", "")

                # 生成 ts_code
                if code.startswith(('60', '68', '90')):
                    ts_code = f"{code}.SH"
                elif code.startswith(('00', '30', '20')):
                    ts_code = f"{code}.SZ"
                elif code.startswith(('8', '4')):
                    ts_code = f"{code}.BJ"
                else:
                    ts_code = f"{code}.SZ"

                # 判断市场
                if code.startswith('000'):
                    market = '主板'
                elif code.startswith('002'):
                    market = '中小板'
                elif code.startswith('300') or code.startswith('301'):
                    market = '创业板'
                elif code.startswith('60'):
                    market = '主板'
                elif code.startswith('688'):
                    market = '科创板'
                elif code.startswith('8') or code.startswith('4'):
                    market = '北交所'
                else:
                    market = '未知'

                records.append({
                    'symbol': code,
                    'name': name,
                    'ts_code': ts_code,
                    'market': market,
                    'area': '',
                    'industry': '',
                    'list_date': '',
                })

            df = pd.DataFrame(records)
            logger.info(f"智兔 API: 成功获取 {len(df)} 只股票")
            return df

        except Exception as e:
            logger.error(f"智兔 API: get_stock_list 失败: {e}")
            return None

    def get_realtime_quotes(self, source: str = "zhitu") -> Optional[Dict[str, Dict[str, Optional[float]]]]:
        """
        获取实时行情快照
        GET /hs/real/ssjy/{code}?token={token}

        注意：智兔实时接口是单只查询，批量获取效率较低。
        此方法暂不实现批量获取（太慢），返回 None 让系统降级到其他数据源。
        如需单只查询，使用 get_single_realtime_quote()。
        """
        # 全市场实时快照不适合逐只查询，返回 None 降级
        return None

    def get_single_realtime_quote(self, code: str) -> Optional[Dict[str, Optional[float]]]:
        """
        获取单只股票实时行情
        GET /hs/real/ssjy/{code}?token={token}
        """
        if not self.is_available():
            return None

        try:
            code_only = code.split('.')[0].zfill(6)
            url = f"{self.base_url}/hs/real/ssjy/{code_only}?token={self.token}"
            data = self._request(url)
            if data is None:
                return None

            # 检查是否有有效数据（价格可能为0，但字段必须存在）
            if isinstance(data, dict) and 'error' not in data and 'p' in data:
                return {
                    "close": self._safe_float(data.get('p')),
                    "pct_chg": self._safe_float(data.get('zdf')),
                    "amount": self._safe_float(data.get('cje')),
                    "volume": self._safe_float(data.get('v')),
                    "open": self._safe_float(data.get('o')),
                    "high": self._safe_float(data.get('h')),
                    "low": self._safe_float(data.get('l')),
                    "pre_close": self._safe_float(data.get('zs')),
                    "turnover_rate": self._safe_float(data.get('hs')),
                    "total_mv": self._safe_float(data.get('sz')),
                    "circ_mv": self._safe_float(data.get('lt')),
                }
            return None

        except Exception as e:
            logger.error(f"智兔 API: get_single_realtime_quote({code}) 失败: {e}")
            return None

    def get_kline(self, code: str, period: str = "day", limit: int = 120, adj: Optional[str] = None) -> Optional[List[Dict]]:
        """
        获取历史K线数据
        GET /hs/history/{code}/{period}/n?token={token}&st={start}&et={end}

        Args:
            code: 股票代码（如 603296.SH 或 603296）
            period: day/week/month
            limit: 获取条数
            adj: 复权类型（智兔默认前复权，此参数忽略）

        Returns:
            按时间正序排列的列表 [{time, open, high, low, close, volume, amount}]
        """
        if not self.is_available():
            return None

        try:
            # 智兔 API 的 period 映射
            period_map = {"day": "d", "week": "w", "month": "m"}
            zhitu_period = period_map.get(period, period)
            # 如果传入的已经是 d/w/m 格式，直接使用
            if period in ("d", "w", "m"):
                zhitu_period = period

            # 股票代码处理（支持 603296.SH 或 603296 格式）
            stock_code = code.split('.')[0] if '.' in code else code
            # 智兔需要带交易所后缀的代码
            code_only = stock_code.zfill(6)
            if code_only.startswith(('60', '68', '90')):
                full_code = f"{code_only}.SH"
            else:
                full_code = f"{code_only}.SZ"

            # 计算日期范围
            end_date = datetime.now().strftime('%Y%m%d')
            if zhitu_period == 'd':
                days_back = int(limit * 1.5)
            elif zhitu_period == 'w':
                days_back = int(limit * 7 * 1.2)
            else:
                days_back = int(limit * 30 * 1.2)
            start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')

            url = (f"{self.base_url}/hs/history/{full_code}/{zhitu_period}/n"
                   f"?token={self.token}&st={start_date}&et={end_date}")
            data = self._request(url, timeout=15)
            if data is None:
                return None

            # 解析响应
            raw_list = []
            if isinstance(data, list):
                raw_list = data
            elif isinstance(data, dict):
                if data.get("code") == 200 and data.get("data"):
                    raw_list = data["data"]
                elif isinstance(data.get("data"), list):
                    raw_list = data["data"]

            if not raw_list:
                return None

            # 转换为标准格式
            items = []
            for row in raw_list:
                if not isinstance(row, dict):
                    continue
                items.append({
                    "time": str(row.get("t", row.get("d", ""))),
                    "open": self._safe_float(row.get("o")),
                    "high": self._safe_float(row.get("h")),
                    "low": self._safe_float(row.get("l")),
                    "close": self._safe_float(row.get("c")),
                    "volume": self._safe_float(row.get("v")),
                    "amount": self._safe_float(row.get("a")),
                })

            # 按时间正序排列（智兔返回的通常已是正序）
            items.sort(key=lambda x: x["time"])

            # 限制返回条数
            if len(items) > limit:
                items = items[-limit:]

            logger.info(f"智兔 API: get_kline({code}, {period}) 返回 {len(items)} 条")
            return items

        except Exception as e:
            logger.error(f"智兔 API: get_kline({code}, {period}) 失败: {e}")
            return None

    def get_financial_indicators(self, code: str) -> Optional[Dict]:
        """
        获取财务指标数据
        GET /hs/gs/cwzb/{code}?token={token}
        
        返回: PE, PB, ROE, EPS, 营收增长率, 净利润增长率, 资产负债率等
        """
        if not self.is_available():
            return None

        try:
            code_only = code.split('.')[0].zfill(6)
            url = f"{self.base_url}/hs/gs/cwzb/{code_only}?token={self.token}"
            data = self._request(url, timeout=15)
            if data is None:
                return None

            # 解析响应 - 可能是列表（多期数据）或字典
            records = []
            if isinstance(data, list):
                records = data
            elif isinstance(data, dict):
                if data.get("code") == 200 and data.get("data"):
                    records = data["data"] if isinstance(data["data"], list) else [data["data"]]
                elif "error" not in data:
                    records = [data]

            if not records:
                logger.warning(f"智兔 API: get_financial_indicators({code}) 返回空数据")
                return None

            # 取最新一期数据
            latest = records[0] if records else None
            if not latest:
                return None

            def _parse_value(val):
                """解析值，'--' 视为 None"""
                if val is None or val == '' or val == '--' or val == '-':
                    return None
                return self._safe_float(val)

            result = {
                "eps": _parse_value(latest.get("mgsy") or latest.get("jqmg") or latest.get("eps")),
                "bvps": _parse_value(latest.get("mgjz") or latest.get("mgjzad") or latest.get("bvps")),
                "roe": _parse_value(latest.get("jzsy") or latest.get("jqjz") or latest.get("jzcsyl") or latest.get("roe")),
                "revenue_growth": _parse_value(latest.get("zysr") or latest.get("yysrtbzz") or latest.get("revenue_yoy")),
                "profit_growth": _parse_value(latest.get("jlzz") or latest.get("jlrtbzz") or latest.get("net_profit_yoy")),
                "debt_ratio": _parse_value(latest.get("zcfzl") or latest.get("debt_ratio")),
                "gross_margin": _parse_value(latest.get("xsml") or latest.get("zylr") or latest.get("gross_margin")),
                "net_margin": _parse_value(latest.get("xsjl") or latest.get("cblr") or latest.get("net_margin")),
                "report_date": latest.get("date") or latest.get("rq") or latest.get("report_date") or "",
                "source": "zhitu_cwzb",
            }

            logger.info(f"智兔 API: get_financial_indicators({code}) 成功, ROE={result.get('roe')}, EPS={result.get('eps')}")
            return result

        except Exception as e:
            logger.error(f"智兔 API: get_financial_indicators({code}) 失败: {e}")
            return None

    def get_financial_ratios(self, code: str) -> Optional[Dict]:
        """
        获取财务主要指标
        GET /hs/fin/ratios/{code}?token={token}
        
        返回: ROE, 毛利率, 营收增长率, 净利润增长率等
        """
        if not self.is_available():
            return None

        try:
            code_only = code.split('.')[0].zfill(6)
            url = f"{self.base_url}/hs/fin/ratios/{code_only}?token={self.token}"
            data = self._request(url, timeout=15)
            if data is None:
                return None

            # 解析响应
            records = []
            if isinstance(data, list):
                records = data
            elif isinstance(data, dict):
                if data.get("code") == 200 and data.get("data"):
                    records = data["data"] if isinstance(data["data"], list) else [data["data"]]
                elif "error" not in data:
                    records = [data]

            if not records:
                return None

            latest = records[0] if records else None
            if not latest:
                return None

            result = {
                "roe": self._safe_float(latest.get("jzcsyl") or latest.get("jqjzcsyl") or latest.get("roe")),
                "gross_margin": self._safe_float(latest.get("mlv") or latest.get("xsmll") or latest.get("gross_margin")),
                "net_margin": self._safe_float(latest.get("jlv") or latest.get("xsjll") or latest.get("net_margin")),
                "revenue_growth": self._safe_float(latest.get("zyyrsrzz") or latest.get("yysrtbzz") or latest.get("revenue_yoy")),
                "profit_growth": self._safe_float(latest.get("jlrzz") or latest.get("jlrtbzz") or latest.get("net_profit_yoy")),
                "source": "zhitu_ratios",
            }

            logger.info(f"智兔 API: get_financial_ratios({code}) 成功")
            return result

        except Exception as e:
            logger.error(f"智兔 API: get_financial_ratios({code}) 失败: {e}")
            return None

    def get_realtime_pe_pb(self, code: str) -> Optional[Dict]:
        """
        从实时交易接口获取 PE 和 PB（市净率）
        GET /hs/real/ssjy/{code}?token={token}
        
        实时接口返回字段中包含 pe 和 sjl（市净率/PB）
        """
        if not self.is_available():
            return None

        try:
            code_only = code.split('.')[0].zfill(6)
            url = f"{self.base_url}/hs/real/ssjy/{code_only}?token={self.token}"
            data = self._request(url)
            if data is None:
                return None

            # 检查是否有有效数据（价格可能为0，但字段必须存在）
            if isinstance(data, dict) and 'error' not in data and 'p' in data:
                pe = self._safe_float(data.get('pe'))
                pb = self._safe_float(data.get('sjl'))  # 市净率
                price = self._safe_float(data.get('p'))
                total_mv = self._safe_float(data.get('sz'))  # 总市值

                result = {
                    "pe": pe,
                    "pb": pb,
                    "price": price,
                    "total_mv": total_mv,
                    "source": "zhitu_realtime",
                }

                logger.info(f"智兔 API: get_realtime_pe_pb({code}) 成功, PE={pe}, PB={pb}")
                return result

            return None

        except Exception as e:
            logger.error(f"智兔 API: get_realtime_pe_pb({code}) 失败: {e}")
            return None

    def get_comprehensive_financial_data(self, code: str) -> Optional[Dict]:
        """
        综合获取财务数据 - 合并多个接口的结果
        优先使用 cwzb（财务指标），补充 realtime（PE/PB），再补充 ratios
        
        Returns:
            包含 pe, pb, roe, eps, bvps, debt_ratio, gross_margin, net_margin,
            revenue_growth, profit_growth, total_mv, price 等字段的字典
        """
        if not self.is_available():
            return None

        result = {}

        # 1. 从实时接口获取 PE/PB/价格/市值（最快）
        realtime = self.get_realtime_pe_pb(code)
        if realtime:
            result["pe"] = realtime.get("pe")
            result["pb"] = realtime.get("pb")
            result["price"] = realtime.get("price")
            result["total_mv"] = realtime.get("total_mv")

        # 2. 从财务指标接口获取详细数据
        indicators = self.get_financial_indicators(code)
        if indicators:
            result["eps"] = indicators.get("eps")
            result["bvps"] = indicators.get("bvps")
            result["roe"] = indicators.get("roe")
            result["revenue_growth"] = indicators.get("revenue_growth")
            result["profit_growth"] = indicators.get("profit_growth")
            result["debt_ratio"] = indicators.get("debt_ratio")
            result["gross_margin"] = indicators.get("gross_margin")
            result["net_margin"] = indicators.get("net_margin")
            result["report_date"] = indicators.get("report_date")

        # 3. 如果 cwzb 缺少某些字段，用 ratios 补充
        if not indicators or not result.get("roe"):
            ratios = self.get_financial_ratios(code)
            if ratios:
                if not result.get("roe"):
                    result["roe"] = ratios.get("roe")
                if not result.get("gross_margin"):
                    result["gross_margin"] = ratios.get("gross_margin")
                if not result.get("net_margin"):
                    result["net_margin"] = ratios.get("net_margin")
                if not result.get("revenue_growth"):
                    result["revenue_growth"] = ratios.get("revenue_growth")
                if not result.get("profit_growth"):
                    result["profit_growth"] = ratios.get("profit_growth")

        # 计算 PE（如果实时接口没有，用 价格/EPS 计算）
        if not result.get("pe") and result.get("price") and result.get("eps"):
            if result["eps"] > 0:
                result["pe"] = result["price"] / result["eps"]

        # 计算 PB（如果实时接口没有，用 价格/每股净资产 计算）
        if not result.get("pb") and result.get("price") and result.get("bvps"):
            if result["bvps"] > 0:
                result["pb"] = result["price"] / result["bvps"]

        result["source"] = "zhitu"

        # 检查是否有有效数据
        has_data = any(v is not None for k, v in result.items() if k not in ("source", "report_date"))
        if not has_data:
            logger.warning(f"智兔 API: get_comprehensive_financial_data({code}) 所有接口均无有效数据")
            return None

        logger.info(f"智兔 API: 综合财务数据获取成功 {code}, PE={result.get('pe')}, PB={result.get('pb')}, ROE={result.get('roe')}")
        return result

    # ==================== 技术指标接口 ====================

    def get_macd(self, code: str, period: str = "d", limit: int = 120) -> Optional[List[Dict]]:
        """
        获取历史 MACD 数据
        GET /hs/history/macd/{code}/{period}/n?token={token}&st={start}&et={end}

        Returns:
            [{time, dif, dea, macd}, ...] 按时间正序
        """
        if not self.is_available():
            return None
        try:
            full_code = self._to_full_code(code)
            zhitu_period = self._map_period(period)
            start_date, end_date = self._calc_date_range(zhitu_period, limit)

            url = (f"{self.base_url}/hs/history/macd/{full_code}/{zhitu_period}/n"
                   f"?token={self.token}&st={start_date}&et={end_date}")
            data = self._request(url, timeout=15)
            if data is None:
                return None

            raw_list = self._extract_list(data)
            if not raw_list:
                return None

            items = []
            for row in raw_list:
                if not isinstance(row, dict):
                    continue
                items.append({
                    "time": str(row.get("t", "")).split(" ")[0],
                    "dif": self._safe_float(row.get("diff") or row.get("dif") or row.get("DIF")),
                    "dea": self._safe_float(row.get("dea") or row.get("DEA")),
                    "macd": self._safe_float(row.get("macd") or row.get("MACD")),
                })

            items.sort(key=lambda x: x["time"])
            if len(items) > limit:
                items = items[-limit:]

            logger.info(f"智兔 API: get_macd({code}, {period}) 返回 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"智兔 API: get_macd({code}) 失败: {e}")
            return None

    def get_ma(self, code: str, period: str = "d", limit: int = 120) -> Optional[List[Dict]]:
        """
        获取历史 MA（移动平均线）数据
        GET /hs/history/ma/{code}/{period}/n?token={token}&st={start}&et={end}

        Returns:
            [{time, ma5, ma10, ma20, ma30, ma60, ma120, ma250}, ...] 按时间正序
        """
        if not self.is_available():
            return None
        try:
            full_code = self._to_full_code(code)
            zhitu_period = self._map_period(period)
            start_date, end_date = self._calc_date_range(zhitu_period, limit)

            url = (f"{self.base_url}/hs/history/ma/{full_code}/{zhitu_period}/n"
                   f"?token={self.token}&st={start_date}&et={end_date}")
            data = self._request(url, timeout=15)
            if data is None:
                return None

            raw_list = self._extract_list(data)
            if not raw_list:
                return None

            items = []
            for row in raw_list:
                if not isinstance(row, dict):
                    continue
                items.append({
                    "time": str(row.get("t", "")).split(" ")[0],
                    "ma5": self._safe_float(row.get("ma5")),
                    "ma10": self._safe_float(row.get("ma10")),
                    "ma20": self._safe_float(row.get("ma20")),
                    "ma30": self._safe_float(row.get("ma30")),
                    "ma60": self._safe_float(row.get("ma60")),
                    "ma120": self._safe_float(row.get("ma120")),
                    "ma250": self._safe_float(row.get("ma250")),
                })

            items.sort(key=lambda x: x["time"])
            if len(items) > limit:
                items = items[-limit:]

            logger.info(f"智兔 API: get_ma({code}, {period}) 返回 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"智兔 API: get_ma({code}) 失败: {e}")
            return None

    def get_boll(self, code: str, period: str = "d", limit: int = 120) -> Optional[List[Dict]]:
        """
        获取历史 BOLL（布林带）数据
        GET /hs/history/boll/{code}/{period}/n?token={token}&st={start}&et={end}

        Returns:
            [{time, upper, mid, lower}, ...] 按时间正序
        """
        if not self.is_available():
            return None
        try:
            full_code = self._to_full_code(code)
            zhitu_period = self._map_period(period)
            start_date, end_date = self._calc_date_range(zhitu_period, limit)

            url = (f"{self.base_url}/hs/history/boll/{full_code}/{zhitu_period}/n"
                   f"?token={self.token}&st={start_date}&et={end_date}")
            data = self._request(url, timeout=15)
            if data is None:
                return None

            raw_list = self._extract_list(data)
            if not raw_list:
                return None

            items = []
            for row in raw_list:
                if not isinstance(row, dict):
                    continue
                items.append({
                    "time": str(row.get("t", "")).split(" ")[0],
                    "upper": self._safe_float(row.get("u") or row.get("upper")),
                    "mid": self._safe_float(row.get("m") or row.get("mid")),
                    "lower": self._safe_float(row.get("d") or row.get("lower")),
                })

            items.sort(key=lambda x: x["time"])
            if len(items) > limit:
                items = items[-limit:]

            logger.info(f"智兔 API: get_boll({code}, {period}) 返回 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"智兔 API: get_boll({code}) 失败: {e}")
            return None

    def get_kdj(self, code: str, period: str = "d", limit: int = 120) -> Optional[List[Dict]]:
        """
        获取历史 KDJ 数据
        GET /hs/history/kdj/{code}/{period}/n?token={token}&st={start}&et={end}

        Returns:
            [{time, k, d, j}, ...] 按时间正序
        """
        if not self.is_available():
            return None
        try:
            full_code = self._to_full_code(code)
            zhitu_period = self._map_period(period)
            start_date, end_date = self._calc_date_range(zhitu_period, limit)

            url = (f"{self.base_url}/hs/history/kdj/{full_code}/{zhitu_period}/n"
                   f"?token={self.token}&st={start_date}&et={end_date}")
            data = self._request(url, timeout=15)
            if data is None:
                return None

            raw_list = self._extract_list(data)
            if not raw_list:
                return None

            items = []
            for row in raw_list:
                if not isinstance(row, dict):
                    continue
                items.append({
                    "time": str(row.get("t", "")).split(" ")[0],
                    "k": self._safe_float(row.get("k") or row.get("K")),
                    "d": self._safe_float(row.get("d") or row.get("D")),
                    "j": self._safe_float(row.get("j") or row.get("J")),
                })

            items.sort(key=lambda x: x["time"])
            if len(items) > limit:
                items = items[-limit:]

            logger.info(f"智兔 API: get_kdj({code}, {period}) 返回 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"智兔 API: get_kdj({code}) 失败: {e}")
            return None

    # ==================== 资金流向接口 ====================

    def get_money_flow(self, code: str, limit: int = 30) -> Optional[List[Dict]]:
        """
        获取资金流向数据
        GET /hs/history/transaction/{code}?token={token}&lt={limit}

        字段说明：
        - 特大单: 成交金额>=100万 或 成交量>=5000手
        - 大单: 成交金额>=20万 或 成交量>=1000手
        - 中单: 成交金额>=4万 或 成交量>=200手
        - 小单: 其他

        Returns:
            [{time, main_buy_orders, main_sell_orders, big_order_trend,
              change_driver, big_order_diff, ...}, ...] 按时间正序
        """
        if not self.is_available():
            return None
        try:
            code_only = code.split('.')[0].zfill(6)
            url = f"{self.base_url}/hs/history/transaction/{code_only}?token={self.token}&lt={limit}"
            data = self._request(url, timeout=15)
            if data is None:
                return None

            raw_list = self._extract_list(data)
            if not raw_list:
                return None

            items = []
            for row in raw_list:
                if not isinstance(row, dict):
                    continue
                # 计算主力净流入（主买特大单+大单成交额 - 主卖特大单+大单成交额）
                buy_td = self._safe_float(row.get("zmbtdcjzl")) or 0  # 主买特大单成交额
                buy_dd = self._safe_float(row.get("zmbddcjzl")) or 0  # 主买大单成交额
                sell_td = self._safe_float(row.get("zmstdcjzl")) or 0  # 主卖特大单成交额
                sell_dd = self._safe_float(row.get("zmsddcjzl")) or 0  # 主卖大单成交额
                main_buy = buy_td + buy_dd
                main_sell = sell_td + sell_dd
                main_net = main_buy - main_sell

                items.append({
                    "time": str(row.get("t", "")),
                    "main_net_inflow": main_net,  # 主力净流入（特大单+大单）
                    "main_buy": main_buy,  # 主力买入额
                    "main_sell": main_sell,  # 主力卖出额
                    "super_large_net": buy_td - sell_td,  # 特大单净流入
                    "large_net": buy_dd - sell_dd,  # 大单净流入
                    "big_order_trend": self._safe_float(row.get("dddx")),  # 大单动向
                    "change_driver": self._safe_float(row.get("zddy")),  # 涨跌动因
                    "big_order_diff": self._safe_float(row.get("ddcf")),  # 大单差分
                    "main_buy_orders": self._safe_float(row.get("zmbzds")),  # 主买单总单数
                    "main_sell_orders": self._safe_float(row.get("zmszds")),  # 主卖单总单数
                })

            items.sort(key=lambda x: str(x["time"]))
            logger.info(f"智兔 API: get_money_flow({code}) 返回 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"智兔 API: get_money_flow({code}) 失败: {e}")
            return None

    # ==================== 指数行情接口 ====================

    def get_index_realtime(self, index_code: str) -> Optional[Dict]:
        """
        获取指数实时行情
        GET /hz/real/ssjy/{index_code}?token={token}

        Args:
            index_code: 指数代码，如 000001.SH(上证指数), 399001.SZ(深证成指),
                       399006.SZ(创业板指), 000688.SH(科创50)

        Returns:
            {code, name, price, change, change_pct, open, high, low, volume, amount}
        """
        if not self.is_available():
            return None
        try:
            # 智兔指数接口使用 /hz/ 前缀
            url = f"{self.base_url}/hz/real/ssjy/{index_code}?token={self.token}"
            data = self._request(url)
            if data is None:
                return None

            # 检查是否有有效数据（价格可能为0，但字段必须存在）
            if isinstance(data, dict) and 'p' in data:
                return {
                    "code": index_code,
                    "name": data.get("mc", ""),
                    "price": self._safe_float(data.get("p")),
                    "change": self._safe_float(data.get("ud")),  # 涨跌额
                    "change_pct": self._safe_float(data.get("pc")),  # 涨跌幅（小数）
                    "open": self._safe_float(data.get("o")),
                    "high": self._safe_float(data.get("h")),
                    "low": self._safe_float(data.get("l")),
                    "volume": self._safe_float(data.get("v")),
                    "amount": self._safe_float(data.get("cje")),
                    "pre_close": self._safe_float(data.get("yc")),
                }
            return None
        except Exception as e:
            logger.error(f"智兔 API: get_index_realtime({index_code}) 失败: {e}")
            return None

    def get_market_overview(self) -> Optional[Dict]:
        """
        获取市场概览（主要指数实时行情）

        Returns:
            {
                "shanghai": {...},   # 上证指数
                "shenzhen": {...},   # 深证成指
                "chinext": {...},    # 创业板指
                "star50": {...},     # 科创50
            }
        """
        if not self.is_available():
            return None

        indices = {
            "shanghai": "000001.SH",   # 上证指数
            "shenzhen": "399001.SZ",   # 深证成指
            "chinext": "399006.SZ",    # 创业板指
            "star50": "000688.SH",     # 科创50
        }

        result = {}
        for name, code in indices.items():
            data = self.get_index_realtime(code)
            if data:
                result[name] = data

        if not result:
            return None

        logger.info(f"智兔 API: get_market_overview() 获取 {len(result)} 个指数")
        return result

    # ==================== 公司简介接口 ====================

    def get_company_profile(self, code: str) -> Optional[Dict]:
        """
        获取上市公司简介
        GET /hs/gs/gsjj/{code}?token={token}

        Returns:
            {name, market, industry, idea, bscope, desc, ldate, ...}
        """
        if not self.is_available():
            return None
        try:
            code_only = code.split('.')[0].zfill(6)
            url = f"{self.base_url}/hs/gs/gsjj/{code_only}?token={self.token}"
            data = self._request(url, timeout=15)
            if data is None:
                return None

            # 响应可能是列表（取第一个）或字典
            profile = None
            if isinstance(data, list) and data:
                profile = data[0]
            elif isinstance(data, dict):
                if data.get("code") == 200 and data.get("data"):
                    d = data["data"]
                    profile = d[0] if isinstance(d, list) and d else d
                elif data.get("name"):
                    profile = data

            if not profile:
                return None

            result = {
                "name": profile.get("name", ""),           # 公司名称
                "ename": profile.get("ename", ""),         # 英文名称
                "market": profile.get("market", ""),       # 上市市场
                "idea": profile.get("idea", ""),           # 概念及板块
                "ldate": profile.get("ldate", ""),         # 上市日期
                "bscope": profile.get("bscope", ""),       # 经营范围
                "desc": profile.get("desc", ""),           # 公司简介
                "instype": profile.get("instype", ""),     # 机构类型/行业
                "organ": profile.get("organ", ""),         # 企业性质
                "addr": profile.get("addr", ""),           # 注册地址
                "site": profile.get("site", ""),           # 公司网站
                "source": "zhitu_gsjj",
            }

            logger.info(f"智兔 API: get_company_profile({code}) 成功, 公司={result['name']}, 概念={result['idea'][:50]}")
            return result
        except Exception as e:
            logger.error(f"智兔 API: get_company_profile({code}) 失败: {e}")
            return None

    # ==================== 辅助方法 ====================

    def _to_full_code(self, code: str) -> str:
        """将股票代码转换为带交易所后缀的格式（如 000001.SZ）"""
        if '.' in code:
            return code
        code_only = code.zfill(6)
        if code_only.startswith(('60', '68', '90')):
            return f"{code_only}.SH"
        return f"{code_only}.SZ"

    def _map_period(self, period: str) -> str:
        """将周期参数映射为智兔 API 格式"""
        period_map = {"day": "d", "week": "w", "month": "m", "year": "y"}
        return period_map.get(period, period)

    def _calc_date_range(self, zhitu_period: str, limit: int) -> tuple:
        """根据周期和条数计算日期范围"""
        end_date = datetime.now().strftime('%Y%m%d')
        if zhitu_period == 'd':
            days_back = int(limit * 1.5)
        elif zhitu_period == 'w':
            days_back = int(limit * 7 * 1.2)
        elif zhitu_period == 'm':
            days_back = int(limit * 30 * 1.2)
        else:
            days_back = int(limit * 365 * 1.2)
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')
        return start_date, end_date

    def _extract_list(self, data) -> list:
        """从 API 响应中提取列表数据"""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if data.get("code") == 200 and data.get("data"):
                return data["data"] if isinstance(data["data"], list) else [data["data"]]
            if isinstance(data.get("data"), list):
                return data["data"]
        return []

    def get_daily_basic(self, trade_date: str) -> Optional[pd.DataFrame]:
        """智兔 API 不支持每日基础财务数据，返回 None 降级到其他数据源"""
        return None

    def find_latest_trade_date(self) -> Optional[str]:
        """通过获取某只股票的最新K线日期来推断最新交易日"""
        if not self.is_available():
            return None

        try:
            # 用上证指数或平安银行来推断最新交易日
            kline = self.get_kline("000001.SZ", period="day", limit=5)
            if kline and len(kline) > 0:
                latest_date = kline[-1].get("time", "")
                if latest_date:
                    # 转换为 YYYYMMDD 格式
                    return latest_date.replace("-", "")
            return None
        except Exception as e:
            logger.error(f"智兔 API: find_latest_trade_date 失败: {e}")
            return None

    def get_news(self, code: str, days: int = 2, limit: int = 50, include_announcements: bool = True):
        """智兔 API 不支持新闻数据，返回 None 降级到其他数据源"""
        return None
