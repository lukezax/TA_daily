# 股票筛选分析流水线

自动化工具：每个交易日执行 B1 策略筛选 → TradingAgents AI 深度分析 → 生成 Web 报告。

## 快速开始

```bash
# 1. 安装依赖
pip install -r pipeline/requirements.txt

# 2. 配置（编辑 pipeline_config.yaml，确保 api_username/api_password 正确）
#    默认配置已可用，无需修改

# 3. 一条命令启动（后台持续运行，365 天自动执行）
nohup python -m pipeline.main --run &

# 查看日志
tail -f pipeline.log
```

## 命令参数

```bash
python -m pipeline.main [选项]
```

| 参数 | 说明 |
|------|------|
| `--run` | **推荐**。完整模式：立即执行一次 + 启动定时调度 + HTTP 报告服务 |
| `--now` | 仅立即执行一次流水线 |
| `--serve` | 仅启动 HTTP 报告服务 |
| `--schedule` | 仅启动定时调度（不含 HTTP 服务） |
| `--time HH:MM` | 指定每日触发时间，覆盖配置文件（如 `--time 23:00`） |
| `--config PATH` | 指定配置文件路径（默认 `pipeline_config.yaml`） |

## 使用示例

```bash
# 每天凌晨 1 点触发（默认），后台持续运行
nohup python -m pipeline.main --run &

# 改成前一天晚上 23 点触发（收盘后更早拿到报告）
nohup python -m pipeline.main --run --time 23:00 &

# 改成凌晨 2 点半触发
nohup python -m pipeline.main --run --time 02:30 &

# 仅手动执行一次（不启动调度）
python -m pipeline.main --now

# 仅启动 HTTP 服务查看已有报告
python -m pipeline.main --serve
```

## 交易日判断规则

调度器每天都会在指定时间触发，但内部自动判断是否为 A 股交易日：

- **交易日** = 周一到周五 且 不是法定节假日
- **非交易日** = 周六/周日（即使调休补班也不开市）+ 法定节假日（春节、国庆等）
- 使用 `chinese-calendar` 库自动获取中国法定节假日数据

**触发时间与目标日期的关系：**

| 触发时间 | 目标交易日 | 说明 |
|---------|-----------|------|
| `--time 01:00`（凌晨） | 今天 | 为今天开盘做准备 |
| `--time 23:00`（晚上） | 明天 | 为明天开盘做准备 |

示例：
- 周四 23:00 触发 → 目标是周五 → 周五是交易日 → 执行
- 周五 23:00 触发 → 目标是周六 → 周六不是交易日 → 跳过
- 周日 23:00 触发 → 目标是周一 → 周一是交易日 → 执行
- 周一 01:00 触发 → 目标是周一 → 周一是交易日 → 执行
- 国庆假期 01:00 触发 → 目标是今天 → 今天是节假日 → 跳过

## 报告访问

启动后通过局域网浏览器访问：

```
http://你的服务器IP:8080
```

- 首页：历史报告列表（按日期倒序）
- 点击日期进入当天报告
- 每只股票可展开查看详细数据和 AI 分析
- 适配 PC / iPhone / iPad

## 配置文件

`pipeline_config.yaml`：

```yaml
pipeline:
  api_base_url: "http://localhost:8000"
  api_username: "admin"          # 必需
  api_password: "admin123"       # 必需
  batch_size: 2                  # 每批提交 2 只（减少资源争抢）
  timeout_per_stock: 10800       # 每只超时 3 小时
  report_output_dir: "./reports"
  server_port: 8080
  tradingagents_results_dir: "./TradingAgents-CN/results"
  strategy: "b1"
  research_depth: "深度"
  selected_analysts: [market, fundamentals, news, social]
  schedule_time: "01:00"         # 可被 --time 参数覆盖
```

## 前置条件

1. **TradingAgents-CN 服务运行中**（`http://localhost:8000`）
2. **stock_filter.py 及其依赖可用**（智兔 API token 已配置）
3. **Python 3.10+**
4. **MongoDB 和 Redis 运行中**（TradingAgents 依赖）

## 流水线执行流程

```
触发 → 判断是否交易日 → 执行 B1 筛选 → 生成初始报告
  → 提交 AI 分析（每批 2 只）→ 每批完成后更新报告
  → 所有批次完成 → 重试失败的股票 → 最终报告
```

**Fallback 机制：**
- TradingAgents 不可用 → 跳过 AI 分析，仅生成筛选报告
- 单只分析失败 → 标记失败，继续其他
- 所有分析失败 → 仍生成完整筛选报告

## 停止服务

```bash
# 找到进程
ps aux | grep "pipeline.main"

# 停止
kill <PID>
```

## 日志

- 控制台输出 + `pipeline.log` 文件
- 格式：`[时间] [级别] [组件] 消息`
- TradingAgents 日志：`TradingAgents-CN/logs/tradingagents.log`
