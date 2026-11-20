"""本地 LLM 调用封装 - 直接调用 llama.cpp"""

import json
import os
import logging
from openai import OpenAI

from strategy_researcher.config import RESEARCHER_CONFIG

logger = logging.getLogger("strategy_researcher.llm")

# 代理环境变量 key 列表
_PROXY_ENV_KEYS = ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")


class LocalLLMClient:
    """本地 llama.cpp LLM 客户端"""

    def __init__(self):
        # 本地 LLM 不需要代理，临时清除 socks 代理避免 httpx 报错
        saved = {k: os.environ.pop(k) for k in _PROXY_ENV_KEYS if k in os.environ}
        try:
            self.client = OpenAI(
                base_url=RESEARCHER_CONFIG["llm_base_url"],
                api_key="not-needed",
                timeout=RESEARCHER_CONFIG["llm_timeout"],
            )
        finally:
            os.environ.update(saved)
        self.model = RESEARCHER_CONFIG["llm_model"]
        self.temperature = RESEARCHER_CONFIG["llm_temperature"]
        self.max_retries = RESEARCHER_CONFIG.get("llm_max_retries", 3)

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """单轮对话，返回文本。空返回会重试，耗尽后抛错，避免静默写入空分析。"""
        retries = getattr(self, "max_retries", 3)
        last_error = None
        for attempt in range(retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=self.temperature,
                    max_tokens=4096,
                )
                content = response.choices[0].message.content
                if content and content.strip():
                    logger.debug("LLM 响应长度: %d", len(content))
                    return content
                last_error = RuntimeError("LLM 返回空内容")
                logger.warning("LLM 返回空内容（第 %d/%d 次）", attempt + 1, retries)
            except Exception as e:
                last_error = e
                logger.error("LLM 调用失败（第 %d/%d 次）: %s", attempt + 1, retries, e)
        raise RuntimeError(f"LLM 调用失败（重试 {retries} 次）：{last_error}")

    def analyze_with_cot(self, data: dict, question: str) -> dict:
        """CoT 分析：强制按 数据→推理→结论 格式输出"""
        system_prompt = """你是一位量化策略研究员。你的职责是分析股票筛选策略的表现，识别问题，提出优化建议。

背景：本系统不实际下单，只做筛选策略的表现复盘与方向研判，输出用于人工参考，不是交易指令。

铁律：
1. 每个结论必须引用具体数据（哪个日期、哪个文件、具体数字）
2. 不允许编造数据。如果数据不足，明确说"数据不足，无法判断"
3. 推理过程必须按 "数据 → 推理 → 结论" 格式
4. 优化建议必须附带可验证的预期效果
5. 区分"确定的发现"和"需要更多数据验证的假设"
6. 样本量门槛：样本少于 30 只时，不得写"策略失效/最优/反转"，只能写"样本不足，暂不判断"
7. 数据质量预检：先检查跨天验证样本数与历史报告是否口径一致、是否存在未分类样本；若数据可疑，先写"数据质量异常"并停止下结论
8. 历史对账：引用历史上下文时，若本次结论与既往 insight 相反，必须显式说明是"新证据推翻旧结论"还是"小样本噪声"，不得直接覆盖
9. 结论必须标注样本量、平均收益、胜率与置信区间（如可得）

输出格式（严格遵循）：

## 数据摘要
（列出关键数据点，标注来源）

## 分析推理
（基于数据的逻辑推导）

## 结论
（明确结论，标注置信度：高/中/低）

## 异常模式
（如果发现异常，描述模式和可能原因）

## 优化方向
（如果有优化建议，附带数据支撑和预期效果）

## 需要外部信息
（如果需要搜索外部资料来辅助分析，列出搜索查询和原因。如果不需要，写"无"）
格式：
- query: "搜索关键词"
  reason: "为什么需要这个信息"
"""

        # 构造用户 prompt
        data_str = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        user_prompt = f"""请分析以下策略数据：

{data_str}

分析问题：{question}

请严格按照系统提示中的格式输出。"""

        response = self.chat(system_prompt, user_prompt)

        # 解析响应，提取结构化信息
        result = {
            "raw_analysis": response,
            "needs_external_info": [],
            "new_insights": [],
            "recommendations": [],
        }

        # 尝试提取"需要外部信息"部分
        if "需要外部信息" in response:
            info_section = response.split("需要外部信息")[-1]
            if "query:" in info_section.lower() or "搜索" in info_section:
                # 简单提取查询
                import re
                queries = re.findall(r'query:\s*["\']([^"\']+)["\']', info_section)
                reasons = re.findall(r'reason:\s*["\']([^"\']+)["\']', info_section)
                for i, q in enumerate(queries):
                    result["needs_external_info"].append({
                        "query": q,
                        "reason": reasons[i] if i < len(reasons) else "",
                    })

        return result
