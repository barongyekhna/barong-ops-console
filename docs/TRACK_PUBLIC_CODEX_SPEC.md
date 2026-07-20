# 买家自助物流查询 · 对外只读端点 · Codex 规格 v1

> 目标:独立站的 "Track your order" 页面改成**双模式**——已登录买家打开就看到自己的订单卡片,点开就地展开物流时间线;未登录游客仍走「订单号 + 邮箱」查询。轨迹数据在控制台(W-S 已接 17TRACK),网站按订单号来问,控制台只答轨迹。
> 分工:**Codex = 控制台对外只读端点 + 测试**;Claude = WP 瘦插件、页面改造、家规 CSS、nginx 放行、env 注入、本地 docker WP 验证、端到端联调。无远程仓库不 push。

## 0. 归属:**不新建模块**

功能挂在**已有的 W-S 物流网络中枢**(`backend/app/modules/w_series/`)。`w_orders` 表已经具备全部所需字段,**本任务不需要任何数据库迁移**:

| 已有字段 | 用途 |
|---|---|
| `order_number` | 查询键(网站按它来问) |
| `tracking_number` / `carrier_code` | 运单号 / 承运商代码 |
| `tracking_status` | 已归一化状态(见 §3 词表) |
| `tracking_events_json` | 轨迹事件数组(`tracking_events()` 产出,**已按时间倒序**,最多 50 条) |
| `last_tracking_update` | 最后更新时间 |

## 1. 端点

`POST /api/public/track/lookup` —— 无登录态,这是全站第二个公开入口,安全从严(照抄 CS 入站的已验证做法)。

**请求头**
- `X-BY-TRACK-KEY` 必须等于新环境变量 `TRACK_PUBLIC_KEY`(**独立密钥,不复用 `CS_INBOUND_KEY`**,泄露时爆炸半径隔离)。常量时间比较;缺失/不符 → 401,响应体不带原因细节。
- Claude 负责注入生产值。

**请求体**
```json
{ "order_numbers": ["3864", "3855"] }
```
- 必填、非空数组;**最多 20 个**;每个元素 trim 后 ≤64 字符;超限 → 422。
- Pydantic `extra="forbid"`(CS 那轮踩过 relay 多传字段 422 的坑,这里保持严格但契约要冻结准确)。

**限流**:调用方永远是 WP 服务器这**一个 IP**,所以**按 IP 限流没有意义、还会误伤**。请实现**全局限流**:每分钟 ≤600 次,超限 429。(浏览器侧的节流由 Claude 在插件里做。)

## 2. 响应契约(冻结,Claude 按此渲染)

对**每一个请求的订单号都返回一条**(顺序与请求一致),便于站点区分"没查到"与"还没发货":

```json
{
  "results": [
    {
      "order_number": "3864",
      "state": "tracked",
      "tracking_number": "SF1234567890",
      "carrier_code": 100003,
      "tracking_status": "in_transit",
      "last_update": "2026-07-20T10:00:00Z",
      "events": [
        { "time": "2026-07-20T10:00:00Z", "location": "Los Angeles, US", "description": "Arrived at facility" },
        { "time": "2026-07-18T09:00:00Z", "location": "Shenzhen, CN", "description": "Picked up" }
      ]
    },
    { "order_number": "9999", "state": "unknown", "tracking_number": null, "carrier_code": null,
      "tracking_status": null, "last_update": null, "events": [] }
  ]
}
```

`state` 三值,**这是站点渲染分支的依据**:
- `tracked` —— 控制台有这单**且**已填运单号(events 可能为空数组,表示刚登记还没有轨迹)
- `not_shipped` —— 控制台有这单但**还没填运单号**(站点显示"仍在备货/待发货")
- `unknown` —— 控制台没有这单(站点显示"暂无物流信息",不要暴露"这单不存在")

`events` 保持 `tracking_events_json` 的原始顺序(**时间倒序,最新在前**),原样透出,不要重排。

## 3. 状态词表(原样透出,勿新增)
`not_found` | `info_received` | `in_transit` | `out_for_delivery` | `delivered` | `exception` | `expired`
(即 `logistics.normalize_tracking_status` 的产出;站点自己做文案映射。)

## 4. 【安全红线】响应绝不含任何个人信息

**只准返回上表字段。** 严禁出现:`customer_name`、任何邮箱/电话/地址、`total`/`currency`、`items_json`、`woo_status`、内部 UUID(`w_orders.id`)。

理由:控制台的订单表本来就没有客户邮箱,天然对不上人;把这条守住,**即使密钥泄露,攻击者拿到的也只是"某个号码的包裹到哪了"**。请在测试里显式断言这些字段不出现(见 §6)。

## 5. 不做的事(边界)
- **不实时调 17TRACK**:一律读库(`tracking_events_json`)。轨迹新鲜度由既有的 webhook / refresh 机制负责,这个端点必须快且不烧配额。
- 不做分页、不做搜索、不接受按邮箱/客户查询(认人是 WordPress 的职责,控制台永远只按订单号答题)。
- 不动 W-S 现有的任何接口、UI 和 `writeback` 逻辑。

## 6. 测试(`bash scripts/run_backend_tests.sh unit` 全绿)
- 无 key / 错 key → 401,且响应体不含原因细节
- 正确 key + 混合订单号 → `results` 长度与顺序同请求;三种 `state` 各覆盖一次
- **PII 断言**:对一条有 `customer_name` / `total` / `items_json` 的订单发起查询,断言响应 JSON 里**不出现**这些值(字符串级断言,防止将来有人顺手加字段)
- 21 个订单号 → 422;空数组 → 422;超长订单号 → 422
- 全局限流触发 → 429
- events 顺序与库中一致(不被重排)

## 硬约束
- **不新建模块、不写迁移**(`w_orders` 字段已够用);别动 Claude 的 WP 插件目录 `backend/app/modules/p_series/wordpress/plugins/`;**别动 F 系列**。
- 新增公开路径**不走前端代理**,无需登记前端白名单(nginx 由 Claude 放行)。
- fail-safe:任何单个订单查询出错都不能让整个请求 500,该条降级成 `state: "unknown"`。

## 交付
本地提交 + 测试绿 + 每任务一句根因/做法。交付后 Claude 接管:env 注入 → nginx 放行 → 瘦插件(**本地 docker WP 先跑通**)→ 页面改造 → 拿真实运单号端到端验证。
