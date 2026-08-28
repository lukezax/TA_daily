# 外网设备接入运行手册（供 AI 助手按步骤执行）

> **本文档的目标读者是 AI 助手**。你的任务：在这台外网设备上完成 Tailscale 环境搭建，
> 打通到公司内网大模型的访问链路，并验证可用。
>
> **执行纪律**：严格按顺序执行，每步末尾有验证门（✅ 预期输出）。验证不过就进入第 7 节故障表，
> 不要跳步、不要猜。遇到标注 👤 的步骤需要人类介入，把提示内容原样转述给用户并等待。

---

## 0. 目标与已知事实

最终交付物：这台设备上任何 OpenAI 兼容客户端能用以下配置正常对话。

| 项 | 值 |
|---|---|
| Base URL | `http://100.127.30.80:22222/v1` |
| API Key | 任意非空字符串（如 `sk-local`），服务端不校验 |
| Model ID | `Qwen3.5-122B-A10B-w4a8` 或 `Qwen3.5-122B-A10B-w4a8-nothinking` |

网络原理（只需了解，无需操作）：该地址是 Tailscale 虚拟网络内的私有 IP，
只有安装了 Tailscale 并加入指定 tailnet 的设备才能路由到它。公网不可达。

安全红线：
- 本文档不含任何真实密钥/密码，**不要**向用户索要除 tailnet 登录以外的任何凭证
- 不要尝试修改远端服务，只做本机环境搭建与连通性验证
- 完成后不要将 Base URL 传播给未授权第三方

---

## 1. 环境探测

先收集信息再动手：

```bash
uname -s          # Linux / Darwin(macOS) / Windows(在 PowerShell 里则是 $env:OS 或 systeminfo)
tailscale version # 检查是否已装
```

判定分支：
- `tailscale version` 有输出 → 跳到第 3 步
- 提示 command not found → 按第 2 步安装

同时确认有 sudo/administrator 权限（安装需要）。没有则直接停止并向用户报告。

---

## 2. 安装 Tailscale

### Linux (Debian/Ubuntu)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

### macOS

```bash
brew install --cask tailscale
# 无 brew 时：引导用户从 App Store 安装 "Tailscale"
```

### Windows

引导用户下载安装：<https://tailscale.com/download/windows>
（AI 无法替用户点 GUI，给出链接并等待）

✅ 验证门：`tailscale version` 输出版本号。

---

## 3. 加入 tailnet（👤 需要人类介入）

```bash
sudo tailscale up
# Windows/macOS：打开 Tailscale App 点 Log in
```

命令会输出一个 `https://login.tailscale.com/a/xxxxx` 授权链接。

👤 **转述给用户**："请在浏览器打开此链接，登录我们指定的 Tailscale 账号完成授权。
账号由所有者提供，必须与中继节点同账号。"

等待用户确认已完成浏览器授权后继续。

> 若设备上已有其他 tailnet 登录：需要先 `sudo tailscale logout` 再重新 up。
> logout 会断开旧网络，操作前告知用户。

✅ 验证门：

```bash
sudo tailscale status | grep anon-relay-02
```

预期看到一行包含 `anon-relay-02` 和 IP `100.127.30.80`。

- 有输出 → 进入第 4 步
- 无输出但 status 正常 → 说明登错了账号，回到本步开头重新登录正确的账号

---

## 4. 连通性验证

```bash
tailscale ping 100.127.30.80    # 预期 pong；显示 via DERP 或 direct 都算通过
curl -s --max-time 8 http://100.127.30.80:22222/v1/models
```

✅ 验证门：curl 返回 JSON，含两个模型 id：

```json
{"object":"list","data":[{"id":"Qwen3.5-122B-A10B-w4a8",...},{"id":"Qwen3.5-122B-A10B-w4a8-nothinking",...}]}
```

- ping 不通 → 第 7 节 T1
- ping 通但 curl 失败 → 第 7 节 T2

---

## 5. 功能验证（流式推理）

```bash
python3 - <<'EOF'
import json, time, urllib.request

req = urllib.request.Request(
    "http://100.127.30.80:22222/v1/chat/completions",
    data=json.dumps({"model":"Qwen3.5-122B-A10B-w4a8",
        "messages":[{"role":"user","content":"用一句话介绍你自己"}],
        "stream":True,"max_tokens":300}).encode(),
    headers={"Content-Type":"application/json"})
t0=time.time(); first=None; buf=[]
with urllib.request.urlopen(req, timeout=120) as r:
    for raw in r:
        line=raw.decode().strip()
        if not line.startswith("data: "): continue
        p=line[6:]
        if p=="[DONE]": break
        try:
            d=json.loads(p)["choices"][0]["delta"]
            txt=(d.get("content") or "")+(d.get("reasoning_content") or "")
            if txt:
                if first is None: first=time.time()-t0
                buf.append(txt)
        except Exception: pass
print(f"首字延迟 {first:.1f}s, 共 {len(''.join(buf))} 字符")
print("样例:", "".join(buf)[:150])
EOF
```

✅ 验证门：`首字延迟` 为有限数字且 < 15s，字符数 > 0。

⚠️ 已知特性（不是故障）：该模型即使 `-nothinking` 变体也可能把大量 token 写进
`reasoning_content` 字段，`content` 可能为 null。判断成功与否看**总字符数**，别只看 content。

---

## 6. 输出客户端配置

全部验证通过后，向用户提供以下配置（可直接粘贴进任意 OpenAI 兼容客户端）：

```
Base URL : http://100.127.30.80:22222/v1
API Key  : sk-local   （任意非空值均可）
Model    : Qwen3.5-122B-A10B-w4a8            （推理版：先思考后回答，token 消耗大）
           Qwen3.5-122B-A10B-w4a8-nothinking  （快速版：仍可能带少量思考前缀）
```

任务完成。向用户报告：安装结果、ping 延迟类型（direct/DERP）、首字延迟实测值。

---

## 7. 故障决策表

| 编号 | 症状 | 诊断 | 动作 |
|---|---|---|---|
| T1 | `tailscale ping` 无 pong | 未登录/登错账号/tailscaled 未跑 | `sudo tailscale status` 看自身行是否 Logged out；重做第 3 步；Linux 检查 `systemctl status tailscaled` |
| T2 | ping 通但 curl 超时/拒绝 | 出口服务异常（非本设备问题） | 等待 1 分钟重试；仍失败则报告"出口节点离线"，本次任务终止，勿反复轰炸 |
| T3 | curl 返回 502 | 后端模型服务波动（已知偶发） | 等 30s 重试一次；连续 3 次 502 则按 T2 终止 |
| T4 | 流式响应为空但无报错 | 只解析了 content 字段 | 用第 5 步脚本（含 reasoning_content），确认总字符数 |
| T5 | 登录链接打不开/授权失败 | 浏览器网络或账号错误 | 让用户换浏览器/网络重试；确认账号正确性由用户负责 |
| T6 | `sudo tailscale up` 报已有其他 tailnet | 设备已在别的虚拟网络 | 征得用户同意后 `sudo tailscale logout` 再 up |

---

## 8. 汇报模板

结束时按此格式向用户汇报：

```
环境: <OS> / tailscale <版本>
入网: 成功（<direct|DERP> 路径）
连通: HTTP 200, 模型列表 x2
功能: 首字延迟 <X.X>s, 流式字符 <N>
配置: Base URL http://100.127.30.80:22222/v1 已可写入客户端
遗留: 无 / <T编号问题描述>
```

---

> 维护方备注（外网 AI 请忽略）：本文档对应 Plan C 直连架构 v2.1，
> 服务端变更时由所有者更新此文件，版本见服务器 stabTestServer 目录。
