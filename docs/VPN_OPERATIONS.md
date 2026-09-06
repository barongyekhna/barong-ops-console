# VPN 运维手册（core.vpn）

## 链路

```
浏览器 / 控制台 App（Windows、安卓）
  │ /api/backend/vpn/*  带 barong_ops_session cookie（path=/api/backend）
  ▼
[控制台机] nginx 精确 location（deploy/nginx/vpn-status-location.conf）
  ▼
[控制台机] barong-vpn-gateway.service  backend/vpn_gateway.py  127.0.0.1:18766
  │  ① cookie → 127.0.0.1:8000/api/public/auth/me 取 user.id
  │  ② Bearer agent-token + X-Barong-User-ID → 各节点 agent
  │  节点登记簿 /etc/barong-vpn-gateway/nodes.json（示例 deploy/vpn/nodes.example.json）
  ▼
[控制台机] barong-vpn-bridge@<node>.service  ssh -L 127.0.0.1:<LOCAL_PORT> → 节点 127.0.0.1:8765
  ▼
[节点机]   barong-vpn-agent.service  /opt/barong-vpn-agent/agent.py（== backend/vpn_agent.py）
           AmneziaWG awg0，UDP 62000，10.66.66.0/24
```

规则：

- 设备只能由**登录的客户端自己登记**（`POST /api/backend/vpn/devices/enroll`，自带公钥）。没有"手动添加设备"，服务端永不生成客户端私钥。
- 登记响应是 **provisioning schema 2**：除 `device_id/address/preshared_key/dns` 外还带 `node{id,name,endpoint,public_key,mtu,obfuscation{Jc,Jmin,Jmax,S1,S2,S3,S4,H1..H4}}`。客户端据此渲染隧道配置，**不内置任何服务器信息**。节点参数来自 agent `GET /v1/node`（读 `awg show`/`awg showconf`），控制台不存副本。
- 同一设备（同 owner + 同 device_id + 同公钥）重复登记 = 重装或换节点，agent 会**换发新 PSK** 并重新挂 peer。
- **客户端最低版本 0.3.0**（`MIN_AGENT_VERSION`，网关在碰任何节点之前就拒绝，HTTP 426，页面同步给出「下载最新 App」按钮）。0.2.x 的隧道配置在安装时烧死（旧端口 443、不带节点参数），登记只会看起来成功：2026-09-06 一台 0.2.1 的电脑登记了 13 次全 201、从未握手，还顺手把停用的老设备重新启用。老机器的处置只有一条：卸载后重新下载安装、再登记。
- 每用户每节点最多 10 台；地址池 10.66.66.2–254。
- 节点机上的老线路（wg0、`renew_vpn.sh`、`wg_heal*.sh`、ufw 规则、`awg0.conf`）**不归本模块管，不要动**。

## 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/backend/vpn/nodes` | 登记簿 + 每节点实时状态（`ok`/`degraded`/`unreachable`，含 `warnings`） |
| GET | `/api/backend/vpn/status` | 默认节点严格状态（只有 `ok` 才 200；nginx `auth_request` 用它做下载鉴权） |
| GET | `/api/backend/vpn/devices` | 本人跨节点设备列表，每条带 `node_id`；`unavailable_nodes` 列出没答上来的节点 |
| POST | `/api/backend/vpn/devices/enroll` | 本机登记，body 含 `node_id`（缺省 = 第一个启用节点） |
| PATCH | `/api/backend/vpn/devices/{uuid}` | `{"enabled": bool}` 停用/启用 |
| GET | `/api/backend/vpn/downloads/windows` `/android` | 安装包（需登录） |

`POST /api/backend/vpn/devices` 已删除（405）。

## 加一个节点（七步，全部是"加"，不改老东西）

1. **节点机**：装 AmneziaWG，起 `awg-quick@awg0`（UDP 端口、`10.66.66.1/24`、`PostUp/PostDown` 走 `/usr/local/libexec/barong-awg-firewall`），ufw 放行该 UDP 端口。
2. **节点机**：建用户 `barong-vpn-bridge`（nologin），把控制台机 `/var/lib/barong-vpn-bridge/.ssh/id_ed25519.pub` 写进它的 `authorized_keys`，前缀 `restrict,port-forwarding,permitopen="127.0.0.1:8765"`。
3. **节点机**：`/opt/barong-vpn-agent/agent.py` ← 仓库 `backend/vpn_agent.py`；`/etc/barong-vpn-agent/control-token` ← 与控制台机 `/etc/barong-vpn-gateway/agent-token` **同一个** token（0600）；`/etc/systemd/system/barong-vpn-agent.service` ← `deploy/systemd/barong-vpn-agent.service`，把 `--public-host` 改成该节点公网地址；`systemctl enable --now barong-vpn-agent`。
4. **控制台机**：`/etc/barong-vpn-bridge/<node>.env`：`REMOTE_HOST=<节点IP>`、`LOCAL_PORT=<未占用的 187xx>`、`REMOTE_PORT=8765`；把节点 host key 追加进 `/etc/barong-vpn-bridge/known_hosts`（`ssh-keyscan -t ed25519 <节点IP>`）。
5. **控制台机**：`cp deploy/systemd/barong-vpn-bridge@.service /etc/systemd/system/`，可选 drop-in 钉 `IPAddressAllow`；`systemctl enable --now barong-vpn-bridge@<node>`；`curl 127.0.0.1:<LOCAL_PORT>/health` 应回 agent。
6. **控制台机**：`/etc/barong-vpn-gateway/nodes.json` 加一条 `{id,name,region,agent_url:"http://127.0.0.1:<LOCAL_PORT>",enabled,order}`；`systemctl restart barong-vpn-gateway`；`curl 127.0.0.1:18766/health` 应列出 `vpn_agent:<node>: ok`。
7. 页面 VPN → 节点面板出现新节点即完成。客户端在页面上点该节点即可切换（重新登记 + 重写本机隧道配置）。

> 现有第一节点 `us-la` 仍由老的 `barong-vpn-bridge.service`（非模板）承载，本手册写就时未迁移；迁移只需把它 stop/disable，然后按第 4–5 步用模板起 `barong-vpn-bridge@us-la`。

## 升级 agent

```
scp backend/vpn_agent.py root@<节点>:/opt/barong-vpn-agent/agent.py.new
ssh root@<节点> 'cp /opt/barong-vpn-agent/agent.py /opt/barong-vpn-agent/agent.py.pre-<sha> \
  && mv /opt/barong-vpn-agent/agent.py.new /opt/barong-vpn-agent/agent.py \
  && chmod 0755 /opt/barong-vpn-agent/agent.py && systemctl restart barong-vpn-agent \
  && sleep 1 && curl -s 127.0.0.1:8765/health'
```

只重启 agent，不动 `awg-quick@awg0`；已建隧道不断，agent 起来后 30 秒内 reconcile 把 `devices.json` 里 enabled 的 peer 补齐。

## 排障

- 先 `curl 127.0.0.1:18766/health`（控制台机）：哪个 `vpn_agent:<node>` 是 `unavailable` 就去看那条桥 `systemctl status barong-vpn-bridge@<node>`。
- 再 `curl 127.0.0.1:<LOCAL_PORT>/v1/status`：`status:"degraded"` 看 `warnings`（`service_status_unavailable` / `interface_status_unavailable` / `vpn_status_unavailable`）。
- 客户端连不上但页面全绿：节点机 `awg show awg0` 看该设备有没有 peer 和握手；`iptables -L ufw-user-input -v -n | grep dpt:<端口>` 看包有没有到。包数不涨 = 客户端在敲别的门（旧配置）。
- nginx 日志 `/var/log/nginx/ops.barongyekhna.com.access.log` 过滤 `/api/backend/vpn`。

## 客户端

- Windows：`/opt/barong-vpn-windows-app-src/windows`（Go agent + Electron 壳），产物 `releases/windows/`。
- 安卓：`/opt/barong-vpn-windows-app-src/android`（内置 AmneziaWG 内核），产物 `releases/android/`；正式签名钥匙在 `/etc/barong-android-signing/`（**必须另行备份**）。
- 苹果：源码在 `.../apple`，等 Apple Developer 账号。

## 发新版客户端(自动更新)

- **Windows**:`console-app` 里 `npm run dist:win` 产出 `BarongOpsConsoleSetup-<ver>-pilot-x64.exe`、`.blockmap`、`latest.yml`,三个一起放进 `releases/windows/`,并把 nginx `downloads/windows` 的 alias 指到新 exe。已装的 App 启动 30 秒后及每 6 小时读 `/api/backend/vpn/updates/windows/latest.yml`(带控制台会话 cookie),后台下载完弹窗"现在重启安装/下次打开时安装"。VPN 组件版本变化时由壳按 `REQUIRED_AGENT_VERSION` 自动升级。
- **安卓**:`./gradlew :app:assembleRelease`(签名从 `/etc/barong-android-signing` 经环境变量注入)产出 APK,放进 `releases/android/` 并重写 `latest.json`(`version_code` 必须递增)。已装的 App 启动 20 秒后及每 6 小时读 `/api/backend/vpn/updates/android/latest.json`,弹窗"立即更新"→ 系统下载管理器下载(带 cookie)→ 点通知安装。
- 两个更新源和手动下载都在 `auth_request` 门后;安装包内不含任何服务器信息。
