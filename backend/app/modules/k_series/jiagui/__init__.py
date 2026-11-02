"""作图家规基座 v2(jiagui)在控制台这边的部分:风格包注册表 + 选包判定(M0 接口 v1 冻结版第二、三、五部分)。

- models:三张表(基座版本、风格包、每次自动检查)。
- packfile:收包时的自动检查(sha256、安全解包、清单、pack.yaml ↔ pack.json、lint)。要 PyYAML,只在 k-worker 里跑。
- registry:登记、待生效 → 生效 / 驳回、退回旧版、给选包用的注册表视图。不依赖 PyYAML,后端和苏青禾都能用。
- route:route.decide() / validate(),纯标准库;模型只交判断,结论由这里算。
- cli:交接目录收包的那一条命令(在 k-worker 里跑)。

包文件放在持久卷 /var/lib/barong/k-media/jiagui/packs/<包 id>/<版本>/,放进去就不再改;要改就发新版本。
"""
