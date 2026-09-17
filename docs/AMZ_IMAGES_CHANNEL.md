# A 系列图片通道(A5)

殷熊只写 brief、只审图;画由 Codex 桌面版画;传由人传。图片线永远 L1。与 K/I 零交集:自己的表、自己的素材目录、自己的 MCP。

## 一张图的一生

1. **证据** → 殷熊的「同屏输了」建议(同词同货兄弟店 CTR 两倍以上),或人在图片页手动建。
2. **事实表门** → 该产品线的事实表在「出图 brief」这个用途上不够就不建(不够不画)。
3. **brief**(`amz_image_briefs.brief_md`):证据、产品事实、位置职责、必须出现 / 禁止出现、兄弟店差异化硬线、交稿规则。
4. **参考图**(人上传,`amz_image_assets.kind`):实拍图 / 现在的主图 / 兄弟店主图 / 对手缩略图。
5. **唤起 Codex**:图片页按钮 → `codex://new?prompt=…` 预填短指令;Codex 经 MCP `amz_get_image_brief` / `amz_get_reference_images` 拉全文和参考图。
6. **交稿**:Codex `amz_submit_image` 或人手上传,走同一条路 → **四道门**:
   - 格式门(代码):能解码、主图 ≥1000px 正方形;
   - 兄弟店差异化门(代码):dHash 汉明距离 ≥ 12;
   - 同屏门(看图模型):缩略图与对手 / 兄弟店排一行,会不会被点、只改哪一块;
   - 事实门(看图模型):必须出现都在、禁止出现都没有、主图无文字。
   看图模型不通 → 该门 unknown,不拦人。每个 brief 最多 4 轮,到顶交人挑。
7. **选定**:人点「选这张」;驳回必填原因(进硬记忆)。
8. **上线**:人手动传到亚马逊后回来点「标记上线」→ 记基线(该词 14 天 CTR、SQP 点击份额)。
9. **回看**:`image_lookback` 作业每天跑,上线满 14 / 28 天算一次,写 `lookback` 与工作日志(经验库材料)。

## 部署

- 服务 `amz-mcp`(`backend/Dockerfile.amz-mcp`,127.0.0.1:8096),nginx `location ^~ /mcp/amz-images`。
- env:`AMZ_MCP_FILE_SIGNING_KEY`(必填)、`AMZ_MEDIA_ROOT`(默认 /var/lib/barong/amz-media,卷 `console_amz_media_data`,backend 与 amz-mcp 都挂)。
- 看图模型:chatgpt(4sapi)钥匙按四家广州组织绑 amz.ops:`python -m backend.app.modules.amz_series.bind_deepseek --provider chatgpt --execute`。台账桶 `amz_image_gates_chatgpt`(默认 120/天)。
- Codex 配置(个人钥匙与 K 通道同一把):
  ```toml
  [mcp_servers.barong_amz_images]
  url = "https://ops.barongyekhna.com/mcp/amz-images"
  bearer_token_env_var = "BARONG_K_MCP_TOKEN"
  ```
- 启动 / 重启只许 `rm -f -s` + `up -d --no-deps`。

## 权限

Bearer 个人钥匙认人;owner 或有店铺授权才能看;交稿 / 上传参考图 / 选定 / 上线要该店「操作」角色。
