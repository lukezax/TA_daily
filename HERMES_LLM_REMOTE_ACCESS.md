# Hermes 122B 外网访问备忘

通过 Tailscale + Caddy 反向代理，让公司外的设备能访问公司内网的 122B 模型服务。

---

## 1. 拓扑

```
外网设备 ──tailscale隧道──→ 本机(100.108.228.20:22222) ──Caddy反代──→ 内网122B(192.168.200.73:8000)
```

- **本机**：内网服务器，跑 hermes agent 的同时，作为外网进入内网模型的入口
- **Tailscale**：本机和外网设备都装客户端加入同一 tailnet，把本机的 tailscale IP `100.108.228.20` 暴露给虚拟网络
- **Caddy**：跑在本机，监听 `100.108.228.20:22222`，把 OpenAI 兼容请求透明转发到内网模型服务器 192.168.200.73:8000
- **Caddy 同时把 Authorization 头强制改成内网模型服务器的 key**，外网设备不用知道内网 key 是什么

---

## 2. 外网设备的前置条件

外网设备要访问 `100.108.228.20:22222`，**必须**满足两个条件：装 Tailscale 客户端 + 加入本机所在的同一个 tailnet。

### 2.1 为什么必须装 Tailscale

`100.108.228.20` 不是公网 IP，是 Tailscale 虚拟网络（tailnet）里的私有地址。它通过 WireGuard 加密隧道在 node 之间点对点直连（或 DERP 中转打洞失败时），没有公网 DNS、没有端口转发、不能用普通浏览器或裸 curl 直接访问。

只有装了 Tailscale 且登录了**和本机同一个账号**（或本机 owner 把你的设备邀请进 tailnet），你的设备才能路由到 `100.x.x.x` 那个网段。

### 2.2 安装 Tailscale 客户端

| 操作系统 | 安装方式 |
|---|---|
| **macOS** | App Store 搜 "Tailscale" 安装，或 `brew install --cask tailscale` |
| **Windows** | 官网下载 `.exe` 安装包：https://tailscale.com/download/windows |
| **Linux**（Debian/Ubuntu） | `curl -fsSL https://tailscale.com/install.sh \| sh` |
| **Linux**（其他发行版） | 同上脚本会自动识别，或参考 https://tailscale.com/download/linux |
| **iOS / Android** | 应用商店搜 "Tailscale" |
| ** cmdline only（headless 服务器）** | 装完后 `sudo tailscale up` 走浏览器登录验证 |

### 2.3 加入 tailnet

装完客户端后：

1. 打开 Tailscale 客户端，点 **Log in**
2. 浏览器跳转到 Tailscale 官网登录页
3. **用和本机登录时同一个账号登录**（Google / Microsoft / GitHub / 邮箱任选其一，但必须同账号）
4. 客户端显示 "Connected" 即可
5. 可选：在 https://login.tailscale.com/admin/machines 看到本机和外网设备都在列表里，且本机那一行后面的 `100.108.228.20` 就是要用的 IP

### 2.4 验证连通性

外网设备上跑：

```bash
# macOS / Linux
ping 100.108.228.20
tailscale status                            # 应能看到本机那一行

# Windows PowerShell
ping 100.108.228.20
tailscale.exe status
```

ping 通且 `tailscale status` 能列出本机即可，说明已经进入 tailnet。

### 2.5 不想装客户端的替代路径

如果某台设备不方便装 Tailscale（比如公司发的电脑装不了任何 VPN 类软件），只能换方案，本套配置用不了。可选：

| 替代 | 说明 |
|---|---|
| **Tailscale Funnel** | 把内网服务通过 Tailscale 的公网入口暴露出去，任何人不用装客户端都能访问。需要改 Caddyfile + 启用 funnel，详见 [Tailscale Funnel 文档](https://tailscale.com/kb/1223/funnel) |
| **Cloudflare Tunnel** | Caddy 替换为 cloudflared，外网访问走 CF 提供的 https 域名，不用装客户端 |
| **frp + 公网云机** | 你自备一台公网 IP 的云服务器做转发 |

当前这套 22222 方案只有"装 Tailscale"这一条路，别无他法。

---

## 3. 外网设备的连接信息

任何 OpenAI 兼容客户端（LobeChat、Open WebUI、Cherry Studio、hermes-cli、curl 等）填：

| 字段 | 值 |
|---|---|
| Base URL | `http://100.108.228.20:22222/v1` |
| API Key | 任意值（Caddy 会覆盖，写 `sk-anything` 或任意非空字符串即可） |
| Model | `Qwen3.5-122B-A10B-w4a8`（reasoning 版，先输出推理过程）<br>`Qwen3.5-122B-A10B-w4a8-nothinking`（普通版，直接给答案） |

curl 验证：

```bash
# 模型列表
curl http://100.108.228.20:22222/v1/models

# 一次推理（非流式）
curl http://100.108.228.20:22222/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-anything" \
  -d '{"model":"Qwen3.5-122B-A10B-w4a8-nothinking","messages":[{"role":"user","content":"hi"}]}'
```

---

## 4. 落地的文件

都在 `/home/raco/workspace/stabTestServer/caddy/` 下：

| 文件 | 作用 |
|---|---|
| `Caddyfile` | 反代规则：绑 tailscale IP、强制 Authorization、转发到 192.168.200.73:8000 |
| `hermes-llm-proxy.service` | systemd unit，开机自启、崩溃自动重启 |
| `docker-compose.yml` | 早期 docker 方案，**未使用**（docker hub 拉不下来），留作备用 |
| `data/` | Caddy 数据目录（证书、访问日志） |
| `config/` | Caddy 配置缓存 |

systemd unit 已复制到 `/etc/systemd/system/hermes-llm-proxy.service` 并 `enable --now`。

---

## 5. 管理命令

```bash
# 查状态
sudo systemctl status hermes-llm-proxy

# 实时日志（请求、错误都在这里）
sudo journalctl -u hermes-llm-proxy -f

# 改了 Caddyfile 后热重载
sudo systemctl reload hermes-llm-proxy

# 重启 / 停止
sudo systemctl restart hermes-llm-proxy
sudo systemctl stop hermes-llm-proxy
```

访问日志文件：`/home/raco/workspace/stabTestServer/caddy/data/caddy-access.log`

---

## 6. 关键细节（出问题时重点排查）

### 6.1 端口监听验证

正常状态下应该看到：

```
$ ss -tlnp | grep 22222
LISTEN 0 4096  100.108.228.20:22222  0.0.0.0:*
```

**只绑在 tailscale IP 上**，本机其他网卡（包括公司内网 IP）连不到 22222，这是有意为之 —— hermes 同事扫不到这个端口。

### 6.2 tailscale IP 变了怎么办

Tailscale 默认给稳定 IP，但万一变了：

1. 本机跑 `tailscale ip` 拿新 IP
2. 改 Caddyfile 里的 `bind 100.108.228.20` 行
3. `sudo systemctl reload hermes-llm-proxy`
4. 改外网设备 Base URL 用新 IP

### 6.3 模型 reasoning 版本流式响应看起来"空"

`Qwen3.5-122B-A10B-w4a8` 是 reasoning 模型，token 会先吐到 `reasoning_content` 字段，把 max_tokens 耗完后还没开始正经回答。表现：客户端看到一堆思考过程，最后 finish_reason=length，回答字段为空。

解决：要么改用 `-nothinking` 变体，要么把 max_tokens 调到 8000+。

### 6.4 安全提醒

- Caddyfile 里的内网模型 key 是明文存的，已收紧文件权限到 600：
  ```bash
  sudo chmod 600 /home/raco/workspace/stabTestServer/caddy/Caddyfile
  ```
- 整个 22222 只对加入你 tailnet 的设备可见，公网无任何暴露
- 外网设备的 API key 是任意值，泄露了也没用 —— 真正的鉴权是 tailscale 网络层

---

## 7. 备用路线（如果这套方案以后不通）

| 方案 | 入口 | 适合 |
|---|---|---|
| Cloudflare Tunnel | CF 免费提供 | 不想装客户端、想要 https 域名 |
| frp | 自备公网云机 | 想完全自主、不依赖 SaaS |
| pritunl / WireGuard | 自备公网云机 | 多人使用、要 Web 管理 |

当前方案的优势：0 成本（不需要公网云机）、5 分钟部署完毕、P2P 直连低延迟、只暴露在私有虚拟网络里。

---

## 8. 已知的问题

- **35B 模型服务挂了**：`192.168.200.160:8005` 当前返回 502。等它恢复后可以再加一段 Caddyfile 同时暴露，比如绑 22223 转发到 192.168.200.160:8005。
- **Caddy 版本**：系统 apt 装的是 2.6.2，功能足够用，不是最新但够稳。
- **Docker Hub 国内拉不下来**：原计划用 caddy:2-alpine 容器跑，但 `docker.io/registry-1.docker.io` TCP 超时，所以改用 apt 装的原生 caddy。如要还原 docker 方案，先配 docker registry mirror。
