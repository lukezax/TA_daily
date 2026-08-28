"""
报告一致性校验器 - TDD 式校验 + 重新生成
"""
import re
import logging

logger = logging.getLogger(__name__)


class ReportValidator:
    """校验 LLM 生成的报告是否与工具获取的真实数据一致"""

    def __init__(self, llm):
        self.llm = llm
        self.max_retries = 3

    def extract_ground_truth(self, market_report: str, stock_code: str) -> dict:
        """从 market_report 提取 ground truth"""
        result = {"code": stock_code, "name": f"股票{stock_code}", "price": 0.0}

        if not market_report:
            return result

        # 提取公司名称: "**爱乐达（300696）技术分析报告**"
        title_match = re.search(r'\*\*(.+?)（\d{6}）', market_report)
        if title_match:
            result["name"] = title_match.group(1)

        # 提取当前价格: "当前价格：40.00" or "当前价格: ¥40.00"
        price_match = re.search(r'当前价格[：:]\s*[¥]?([\d.]+)', market_report)
        if price_match:
            result["price"] = float(price_match.group(1))

        return result

    def detect_errors(self, content: str, ground_truth: dict) -> list:
        """检测报告中的错误"""
        errors = []
        if not content or not content.strip():
            return errors

        code = ground_truth["code"]
        correct_name = ground_truth["name"]
        correct_price = ground_truth["price"]

        # 1. 检查是否出现了错误的公司名
        # 查找 "（{code}）" 或 "`{code}`" 后面跟的公司名
        name_patterns = [
            rf'[`]?{code}[`]?[）)]\s*[（(]?(.+?)[）)]',
            rf'[`]?{code}[`]?\s*[（(](.+?)[）)]',
            rf'标的\s*[`]?{code}[`]?\s*[（(](.+?)[）)]',
        ]
        for pattern in name_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                if match and match != correct_name and len(match) < 10:
                    errors.append({
                        "type": "wrong_name",
                        "wrong": match,
                        "correct": correct_name,
                    })

        # 2. 检查目标价格是否严重偏离
        if correct_price > 0:
            # 查找目标价: "目标价位: ¥7.15" or "目标价格：7.15元"
            target_patterns = [
                r'目标价[位格]?[：:]\s*[¥￥]?([\d.]+)',
                r'目标[：:]\s*[¥￥]?([\d.]+)',
            ]
            for pattern in target_patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    try:
                        target = float(match)
                        deviation = abs(target - correct_price) / correct_price
                        if deviation > 0.5:  # 偏差超过 50%
                            errors.append({
                                "type": "wrong_price",
                                "wrong": target,
                                "correct": correct_price,
                                "deviation": f"{deviation*100:.0f}%",
                            })
                    except ValueError:
                        pass

        return errors

    def build_correction_prompt(self, original_content: str, errors: list, ground_truth: dict) -> str:
        """构造纠错 prompt"""
        error_descriptions = []
        for e in errors:
            if e["type"] == "wrong_name":
                error_descriptions.append(
                    f"- 你使用了错误的公司名称「{e['wrong']}」，正确名称是「{e['correct']}」"
                )
            elif e["type"] == "wrong_price":
                error_descriptions.append(
                    f"- 你使用了错误的价格 ¥{e['wrong']}，实际当前价格是 ¥{e['correct']}（偏差 {e['deviation']}）"
                )

        error_text = "\n".join(error_descriptions)

        return f"""你之前的分析存在以下事实性错误，请修正后重新输出完整分析：

❌ 检测到的错误：
{error_text}

📌 正确的基础数据（来自实时行情工具验证）：
- 股票代码：{ground_truth['code']}
- 公司名称：{ground_truth['name']}
- 当前价格：¥{ground_truth['price']}

请基于以上正确数据，重新生成你的完整分析。保持原有的分析框架和格式，但确保：
1. 使用正确的公司名称「{ground_truth['name']}」
2. 所有价格分析基于当前价格 ¥{ground_truth['price']}
3. 目标价格应该在当前价格的合理范围内（±30%以内）

以下是你之前的分析（需要修正）：
{original_content}

请输出修正后的完整分析："""

    def validate_and_retry(self, state: dict, report_key: str) -> dict:
        """
        校验报告，错误则让 LLM 重新生成（最多重试 3 次）

        如果 3 次都失败，返回带有 _validation_failed 标记的 state
        """
        content = state.get(report_key, "")
        if not content or not content.strip():
            return state

        ground_truth = self.extract_ground_truth(
            state.get("market_report", ""),
            state.get("company_of_interest", "")
        )

        # 如果无法提取 ground truth，跳过校验
        if ground_truth["price"] == 0.0:
            return state

        errors = self.detect_errors(content, ground_truth)
        if not errors:
            logger.info(f"✅ [{report_key}] 校验通过")
            return state

        # 有错误，开始重试
        for attempt in range(1, self.max_retries + 1):
            logger.warning(
                f"⚠️ [{report_key}] 第 {attempt}/{self.max_retries} 次校验失败: {errors}"
            )

            correction_prompt = self.build_correction_prompt(content, errors, ground_truth)

            try:
                from langchain_core.messages import HumanMessage
                corrected_response = self.llm.invoke([HumanMessage(content=correction_prompt)])
                corrected = corrected_response.content if hasattr(corrected_response, 'content') else str(corrected_response)

                # 再次校验
                new_errors = self.detect_errors(corrected, ground_truth)
                if not new_errors:
                    state[report_key] = corrected
                    logger.info(f"✅ [{report_key}] 第 {attempt} 次修正成功")
                    return state

                # 仍有错误，用修正版本继续下一轮
                content = corrected
                errors = new_errors

            except Exception as e:
                logger.error(f"❌ [{report_key}] 修正调用失败: {e}")

        # 3 次都失败，标记放弃
        logger.error(f"❌ [{report_key}] 3 次修正均失败，放弃 AI 分析")
        state["_validation_failed"] = True
        state["_validation_failure_reason"] = (
            f"报告 {report_key} 经过 3 次修正仍存在数据错误：{errors}。"
            f"正确数据：{ground_truth['name']}({ground_truth['code']})，当前价格 ¥{ground_truth['price']}"
        )
        return state
