# Barong Yekhna 店铺家规 CSS —— 纯 CSS，交给瘦插件全站加载。
# 关键教训：作用域里若含逗号(选择器列表)，绝不能直接拼进后代选择器，
# 否则 "A, B .x" 会拆成独立的 "A" 命中 body 本身。用 rule() 做笛卡尔积安全展开。

def rule(scopes, targets, decl):
    sels = []
    for s in scopes:
        for t in targets:
            sels.append((s + " " + t).strip())
    return ",".join(sels) + "{" + decl + "}"

# 作用域(每个都是单一简单选择器，无逗号)
# 注意：商店页 slug=shop 后被 WP 当"页面"路由，body 类是 woocommerce-shop 而非 post-type-archive-product。
# 用 woocommerce-shop(两种路由都在)才稳；品类归档用 tax-product_cat。
ARCH = ["body.woocommerce-shop", "body.tax-product_cat"]  # 商店主页 + 品类归档
WOO  = ["body.woocommerce"]  # 所有 woo 页(卡片：含单品页的相关产品)

parts = []
# —— 全站：删掉顶部红色促销条(用户嫌丑，促销/免运费信息以后另放)——
parts.append("#top-bar{display:none!important}")
# —— 头部 logo 比例修正:凤凰缩到 56px,居中呼吸 ——
parts.append(".header #logo img,#logo img{max-height:56px!important;width:auto!important;padding:0!important}")
parts.append(".header #logo{display:flex!important;align-items:center!important}")

# ============ 全站基调(家规高大上版 · 覆盖现有与未来所有页面/文章)============
# 原则:首页(body.home)是钦定深色凤凰 Hero,底色不动;其余页面统一亮中性灰 + 墨色标题。
NH = ["body:not(.home)"]  # 单一选择器,无逗号,rule() 安全
# 1) 内容区底色:亮中性灰(与商店/详情页同一张纸)
parts.append(rule(NH, ["#main", "#content", ".page-wrapper"], "background-color:#f4f4f6!important"))
# 2) 标题:墨色 + 系统字(与 PDP 同款),仅内容区,避免碰深色区块
parts.append(rule(NH, ["#main h1", "#main h2", "#main h3", "#main h4"],
    "font-family:-apple-system,system-ui,'Segoe UI',sans-serif!important;color:#1b1a18!important;letter-spacing:-.01em!important"))
parts.append(rule(NH, ["#main .entry-content p", "#main .entry-summary p"], "color:#3d3a36"))
# 3) 按钮/搜索钮:橙红默认色 → 墨黑胶囊(全站)
parts.append(".button.primary,input[type=submit].button,button[type=submit].button,.searchform .submit-button{background-color:#1b1a18!important;border-color:#1b1a18!important;color:#faf9f6!important}")
parts.append(".searchform .submit-button{border-radius:0 10px 10px 0!important}")
parts.append(".searchform input[type=search],.searchform .search-field{border:1px solid #d9d7d3!important;border-radius:10px 0 0 10px!important;background:#fff!important}")
# 4) 头部下拉菜单:白瓷砖 + 墨字(修"看不清")——全站含首页
parts.append(".nav-dropdown{background:#ffffff!important;border:0!important;border-radius:14px!important;box-shadow:0 2px 4px rgba(20,20,30,.06),0 18px 44px -18px rgba(20,20,30,.28)!important;padding:8px!important}")
parts.append(".nav-dropdown li{border:0!important}")
parts.append("ul.nav-dropdown.nav-dropdown-default li.menu-item > a,ul.sub-menu.nav-dropdown li.menu-item > a,.header .nav-dropdown li.menu-item > a,.nav-dropdown li a{color:#1b1a18!important;font-weight:500!important;font-size:14px!important;letter-spacing:.01em!important;border:0!important;border-radius:9px!important;padding:9px 12px!important}")
parts.append("ul.nav-dropdown.nav-dropdown-default li.menu-item > a:hover,ul.sub-menu.nav-dropdown li.menu-item > a:hover,.nav-dropdown li a:hover{background:#f4f4f6!important;color:#000!important}")
parts.append(".nav-dropdown .menu-item > a{text-transform:none!important}")
parts.append("#header .nav-dropdown li a,#header ul.nav-dropdown li.menu-item > a{color:#1b1a18!important}")
parts.append("#header .nav-dropdown li a:hover{color:#000!important}")
# 5) 页脚:高级墨黑 + 柔和链接(全站统一)
parts.append(".absolute-footer,.absolute-footer.dark{background-color:#141312!important;color:#8b867f!important;padding:22px 0!important}")
parts.append(".absolute-footer a,.absolute-footer .menu-item a{color:#a49f98!important}")
parts.append(".absolute-footer a:hover{color:#faf9f6!important}")
parts.append(".footer-wrapper .footer,.footer-widgets{background-color:#141312!important}")
# 5b) 主题演示遗留的社交图标全部指向占位符 http://url(死链)——开真号前全站隐藏
parts.append('a.icon[href="http://url"],a[href="http://url"]{display:none!important}')
# 6) 表单控件全站统一圆角浅边
parts.append(rule(NH, ["#main input[type=text]", "#main input[type=email]", "#main textarea"],
    "border:1px solid #d9d7d3!important;border-radius:10px!important;background:#fff!important"))
# 7) 文章卡片/侧栏轻整理:白瓷砖化
parts.append(rule(NH, ["#main .col-inner .box-blog-post", "#main article.post"],
    "background:#fff!important;border-radius:16px!important;overflow:hidden!important;box-shadow:0 1px 2px rgba(20,20,30,.04),0 12px 30px -16px rgba(20,20,30,.12)!important"))
parts.append(rule(NH, ["#main .widget"], "background:transparent"))
parts.append(rule(NH, ["#main .widget-title", "#main .widget .widget-title"], "color:#1b1a18!important;letter-spacing:.12em!important"))

# ============ by-page(About / Wholesale 等品牌页)============
BP=["body:not(.home)"]
parts.append(rule(BP,[".by-page"],"max-width:960px;margin:0 auto;padding:clamp(28px,5vw,64px) 18px"))
parts.append(rule(BP,[".by-page .by-eyebrow2"],"font-size:11.5px;letter-spacing:.22em;text-transform:uppercase;color:#a49f98;font-weight:700;margin:0 0 10px"))
parts.append(rule(BP,[".by-page h1"],"font-size:clamp(30px,4.6vw,46px)!important;letter-spacing:-.02em!important;margin:0 0 14px!important"))
parts.append(rule(BP,[".by-page .by-lead"],"font-size:17px;line-height:1.7;color:#3d3a36;max-width:640px"))
parts.append(rule(BP,[".by-page .by-hero-lite"],"text-align:center;padding:0 0 clamp(24px,4vw,44px)"))
parts.append(rule(BP,[".by-page .by-hero-lite .by-lead"],"margin:0 auto"))
parts.append(rule(BP,[".by-page .by-block"],"background:#fff;border-radius:20px;box-shadow:0 1px 2px rgba(20,20,30,.04),0 18px 44px -24px rgba(20,20,30,.14);padding:clamp(22px,3.4vw,38px);margin:0 0 22px"))
parts.append(rule(BP,[".by-page .by-block h2"],"margin:0 0 12px!important;font-size:22px!important"))
parts.append(rule(BP,[".by-page .by-cards"],"display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin-top:16px"))
parts.append(rule(BP,[".by-page .by-card"],"background:#f4f4f6;border-radius:14px;padding:18px"))
parts.append(rule(BP,[".by-page .by-card h3"],"font-size:15.5px!important;margin:0 0 8px!important;color:#1b1a18!important"))
parts.append(rule(BP,[".by-page .by-card p"],"font-size:14px;color:#55524e;margin:0;line-height:1.6"))
parts.append(rule(BP,[".by-page .by-list"],"margin:8px 0 0;padding-left:0;list-style:none"))
parts.append(rule(BP,[".by-page .by-list li"],"padding:10px 0 10px 26px;position:relative;border-bottom:1px solid #f0efed"))
parts.append(rule(BP,[".by-page .by-list li:last-child"],"border-bottom:0"))
parts.append(rule(BP,[".by-page .by-list li:before"],"content:'✓';position:absolute;left:2px;color:#1b1a18;font-weight:700"))
parts.append(rule(BP,[".by-page .by-list-x li:before"],"content:'✕';color:#a49f98!important"))

# ---- CS 联系表单(直连控制台)----
parts.append(rule(BP,[".by-cs-form"],"margin-top:6px"))
parts.append(rule(BP,[".by-cs-grid"],"display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px"))
parts.append(rule(BP,[".by-cs-field"],"display:block;margin:0 0 14px"))
parts.append(rule(BP,[".by-cs-field span"],"display:block;font-size:13px;color:#6f6b66;margin:0 0 6px;font-weight:600"))
parts.append(rule(BP,[".by-cs-field input", ".by-cs-field textarea"],"width:100%;border:1px solid #d9d7d3!important;border-radius:12px!important;background:#fff!important;padding:12px 14px!important;font-size:15px!important;box-shadow:none!important"))
parts.append(rule(BP,[".by-cs-field textarea"],"resize:vertical;min-height:130px"))
parts.append(rule(BP,[".by-cs-field input:focus", ".by-cs-field textarea:focus"],"border-color:#1b1a18!important;outline:none!important"))
parts.append(rule(BP,[".by-cs-actions"],"display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-top:4px"))
parts.append(rule(BP,[".by-cs-submit"],"background:#1b1a18!important;color:#faf9f6!important;border:0!important;border-radius:999px!important;padding:13px 30px!important;font-weight:600!important;letter-spacing:.02em!important;cursor:pointer"))
parts.append(rule(BP,[".by-cs-submit:disabled"],"opacity:.55"))
parts.append(rule(BP,[".by-cs-note"],"font-size:13.5px;color:#6f6b66"))
parts.append(rule(BP,[".by-cs-note.ok"],"color:#1f7a4d"))
parts.append(rule(BP,[".by-cs-note.err"],"color:#b3261e"))
parts.append(rule(BP,[".by-page .by-steps"],"margin:8px 0 0;padding-left:0;list-style:none;counter-reset:bstep"))
parts.append(rule(BP,[".by-page .by-steps li"],"counter-increment:bstep;padding:12px 0 12px 44px;position:relative;border-bottom:1px solid #f0efed"))
parts.append(rule(BP,[".by-page .by-steps li:last-child"],"border-bottom:0"))
parts.append(rule(BP,[".by-page .by-steps li:before"],"content:counter(bstep);position:absolute;left:0;top:10px;width:28px;height:28px;border-radius:999px;background:#1b1a18;color:#faf9f6;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700"))
parts.append(rule(BP,[".by-page .by-cta-block"],"text-align:center"))
parts.append(rule(BP,[".by-page .by-btn"],"display:inline-block;background:#1b1a18!important;color:#faf9f6!important;border-radius:999px;padding:13px 30px;font-weight:600;letter-spacing:.02em"))
parts.append(rule(BP,[".by-page a:not(.by-btn)"],"color:#1b1a18;text-decoration:underline"))

# ---- 法务长文页(隐私/条款)专用:中性列表、目录、要点强调 ----
# 勾选号列表不适合法律条文,这里用克制的短横中性符号。
parts.append(rule(BP,[".by-page .by-list-plain"],"margin:10px 0 0;padding-left:0;list-style:none"))
parts.append(rule(BP,[".by-page .by-list-plain li"],"padding:9px 0 9px 20px;position:relative;color:#3d3a36;line-height:1.7"))
parts.append(rule(BP,[".by-page .by-list-plain li:before"],"content:'—';position:absolute;left:0;color:#c3bfb9;font-weight:400"))
parts.append(rule(BP,[".by-page .by-list-plain strong"],"color:#1b1a18;font-weight:600"))
# 正文行距放宽一档:法律条文密度大,读起来才不累
parts.append(rule(BP,[".by-page .by-legal p"],"color:#3d3a36;line-height:1.78;margin:0 0 14px;font-size:15.5px"))
parts.append(rule(BP,[".by-page .by-legal p:last-child"],"margin-bottom:0"))
# "最后更新"元信息
parts.append(rule(BP,[".by-page .by-meta"],"font-size:13px;color:#8b867f;letter-spacing:.02em;margin:14px 0 0"))
# 关键承诺高亮(如"我们不出售你的个人信息")
parts.append(rule(BP,[".by-page .by-highlight"],"background:#f4f4f6;border-left:3px solid #1b1a18;border-radius:8px;padding:16px 20px;margin:16px 0;color:#1b1a18;font-size:15.5px;line-height:1.7;font-weight:500"))
# 目录:长法务页的导航
parts.append(rule(BP,[".by-page .by-toc"],"display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:2px 18px;margin:6px 0 0;padding-left:0;list-style:none;counter-reset:btoc"))
parts.append(rule(BP,[".by-page .by-toc li"],"counter-increment:btoc;padding:7px 0 7px 26px;position:relative"))
parts.append(rule(BP,[".by-page .by-toc li:before"],"content:counter(btoc);position:absolute;left:0;top:7px;font-size:11.5px;color:#a49f98;font-weight:700;letter-spacing:.06em"))
parts.append(rule(BP,[".by-page .by-toc a"],"color:#3d3a36!important;text-decoration:none!important;font-size:14.5px"))
parts.append(rule(BP,[".by-page .by-toc a:hover"],"color:#1b1a18!important;text-decoration:underline!important"))
# 锚点跳转时标题不被吸顶头部盖住
parts.append(rule(BP,[".by-page .by-block[id]"],"scroll-margin-top:100px"))

parts.append("body.page-id-1 .page-title,body.page-id-1792 .page-title,body.page-id-33 .page-title,body.page-id-1436 .page-title,body.page-id-1162 .page-title,body.page-id-1251 .page-title{display:none!important}")
parts.append(".widget li:has(> a[href*=\"/uncategorized\"]),li.cat-item:has(> a[href*=\"/uncategorized\"]){display:none!important}")

# ============ 页脚贴底(治所有短页面"页脚下灰条")============
# #wrapper 撑满视口,#main 弹性填充 —— 404/账户页等短页页脚永远贴底
parts.append("#wrapper{display:flex!important;flex-direction:column!important;min-height:100svh!important}")
parts.append("#wrapper > #main,#wrapper > main{flex:1 0 auto!important}")
parts.append("html,body{background-color:#141312!important}")  # 万一露底也露墨黑(与页脚同色)

# ============ My Account 账户页(顶级化)============
ACC = ["body.woocommerce-account"]
parts.append(rule(ACC, ["#main"], "padding:clamp(28px,5vw,64px) 0!important"))
# 页头标题条:去底、居中收紧
parts.append(rule(ACC, [".my-account-header"], "background:transparent!important;border:0!important;padding:0 0 22px!important"))
parts.append(rule(ACC, [".my-account-header .page-title-inner", ".my-account-header .heading-text"],
    "font-size:30px!important;letter-spacing:-.02em!important;color:#1b1a18!important"))
# 登录/注册双白瓷砖卡
parts.append(rule(ACC, [".account-container"], "max-width:1040px!important;margin:0 auto!important;background:transparent!important;padding:0!important"))
parts.append(rule(ACC, [".account-container .col2-set"], "display:flex!important;flex-wrap:wrap!important;gap:28px!important;justify-content:center!important"))
parts.append(rule(ACC, [".account-container .col2-set > .col"], "flex:1 1 380px!important;max-width:520px!important;padding:0!important;border:0!important"))
parts.append(rule(ACC, [".account-container .row-divided > .col + .col", ".account-container .col2-set .col-2"], "border-left:0!important;border:0!important"))
parts.append(rule(ACC, [".account-login-inner", ".account-register-inner"],
    "background:#fff!important;border-radius:22px!important;box-shadow:0 1px 2px rgba(20,20,30,.04),0 24px 60px -30px rgba(20,20,30,.18)!important;padding:34px 34px 30px!important;height:100%!important"))
parts.append(rule(ACC, [".account-login-inner h3", ".account-register-inner h3", ".account-login-inner .account-login-title", ".account-register-inner .account-login-title"],
    "font-size:20px!important;letter-spacing:-.01em!important;color:#1b1a18!important;margin-bottom:18px!important;border:0!important"))
# 输入框/按钮统一
parts.append(rule(ACC, ["input[type=text]", "input[type=email]", "input[type=password]"],
    "border:1px solid #d9d7d3!important;border-radius:12px!important;height:50px!important;background:#fff!important;box-shadow:none!important"))
parts.append(rule(ACC, ["button[type=submit]", ".woocommerce-button", "button.button"],
    "background:#1b1a18!important;border-color:#1b1a18!important;color:#faf9f6!important;border-radius:999px!important;height:50px!important;padding:0 28px!important;letter-spacing:.04em!important"))
parts.append(rule(ACC, ["form .form-row label"], "color:#6f6b66!important;font-size:13px!important"))
parts.append(rule(ACC, [".lost_password a", ".woocommerce-LostPassword a"], "color:#6f6b66!important;text-decoration:underline!important"))
# Google 登录钮圆角化
parts.append(rule(ACC, [".nsl-container .nsl-button", ".nsl-button-default"],
    "border-radius:999px!important;box-shadow:0 1px 2px rgba(20,20,30,.10)!important"))
# ---- 登录后仪表盘:左侧白瓷砖导航 + 右侧内容瓷砖 ----
parts.append(rule(ACC, [".woocommerce-MyAccount-navigation"],
    "background:#fff!important;border-radius:18px!important;box-shadow:0 1px 2px rgba(20,20,30,.04),0 16px 40px -22px rgba(20,20,30,.16)!important;padding:12px!important"))
parts.append(rule(ACC, [".woocommerce-MyAccount-navigation ul"], "margin:0!important"))
parts.append(rule(ACC, [".woocommerce-MyAccount-navigation ul li"], "border:0!important;list-style:none!important"))
parts.append(rule(ACC, [".woocommerce-MyAccount-navigation ul li a"],
    "display:block!important;padding:11px 16px!important;border-radius:12px!important;color:#3d3a36!important;font-weight:500!important;letter-spacing:.01em!important"))
parts.append(rule(ACC, [".woocommerce-MyAccount-navigation ul li.is-active a", ".woocommerce-MyAccount-navigation ul li a:hover"],
    "background:#f4f4f6!important;color:#1b1a18!important"))
parts.append(rule(ACC, [".woocommerce-MyAccount-content"],
    "background:#fff!important;border-radius:18px!important;box-shadow:0 1px 2px rgba(20,20,30,.04),0 16px 40px -22px rgba(20,20,30,.16)!important;padding:30px!important"))
parts.append(rule(ACC, [".woocommerce-MyAccount-content .woocommerce-table", ".woocommerce-MyAccount-content table"],
    "border:0!important;border-radius:12px!important;overflow:hidden!important"))
parts.append(rule(ACC, [".woocommerce-MyAccount-content table th"], "background:#f4f4f6!important;color:#1b1a18!important;border:0!important"))
parts.append(rule(ACC, [".woocommerce-MyAccount-content table td"], "border-color:#eeedec!important"))
# —— 页面底色:浅中性灰(让暖白产品瓷砖跳出来)——
parts.append(rule(ARCH, ["#content", ".shop-container"], "background:#f4f4f6!important"))
# —— shop 头部极简去杂 ——
parts.append(rule(ARCH, [".shop-page-title.page-title", ".woocommerce-products-header"],
                  "text-align:center!important;border:0!important;padding-top:clamp(24px,4vw,48px)!important"))
parts.append(rule(ARCH, [".shop-page-title .page-title-inner"], "background:transparent!important"))
parts.append(rule(ARCH, [".woocommerce-result-count", ".woocommerce-ordering"], "opacity:.65"))
# —— 隐藏左侧类目侧栏"整根栏"，内容栏撑满(修上轮左侧空白 bug)——
parts.append(rule(ARCH, [".category-page-row > .col.large-3"], "display:none!important"))
parts.append(rule(ARCH, [".category-page-row > .col.large-9"],
                  "flex:0 0 100%!important;max-width:100%!important;width:100%!important"))
# —— 卡片：干净、无重边框、家规排版 ——
parts.append(rule(WOO, [".product-small.box"], "background:transparent!important;border:0!important;box-shadow:none!important"))
parts.append(rule(WOO, [".product-small .box-image"],
                  "border-radius:16px!important;overflow:hidden!important;background:#fff!important;box-shadow:0 1px 2px rgba(20,20,30,.04),0 12px 30px -16px rgba(20,20,30,.14)!important;transition:transform .32s cubic-bezier(.2,.6,.2,1),box-shadow .32s ease!important"))
parts.append(rule(WOO, [".product-small.box:hover .box-image"],
                  "transform:translateY(-6px)!important;box-shadow:0 3px 6px rgba(20,20,30,.05),0 26px 50px -22px rgba(20,20,30,.22)!important"))
parts.append(rule(WOO, [".product-small .box-image img"], "transform:none!important"))
parts.append(rule(WOO, [".product-small .box-text"], "text-align:left!important;padding:14px 2px 0!important"))
parts.append(rule(WOO, [".product-small .box-text .category"],
                  "font-size:10.5px!important;letter-spacing:.16em!important;text-transform:uppercase!important;color:#a49f98!important;font-weight:700!important;opacity:1!important;margin:0 0 4px!important"))
parts.append(rule(WOO, [".product-small .box-text .name.product-title"], "margin:0!important"))
parts.append(rule(WOO, [".product-small .box-text .name.product-title a"],
                  "font-family:-apple-system,system-ui,'Segoe UI',sans-serif!important;font-size:17px!important;font-weight:500!important;letter-spacing:-.01em!important;color:#1b1a18!important"))
parts.append(rule(WOO, [".product-small .price"],
                  "font-family:-apple-system,system-ui,sans-serif!important;font-size:15px!important;color:#6f6b66!important"))
parts.append(rule(WOO, [".product-small .price ins"], "text-decoration:none!important;color:#1b1a18!important;font-weight:500!important"))
parts.append(rule(WOO, [".product-small .price del"], "color:#a49f98!important;font-size:13px!important"))
# —— Sale 角标：极简黑色小胶囊(改 Flatsome 外层 badge-inner，别只改内层 span)——
parts.append(rule(WOO, [".product-small .badge.badge-circle", ".product-small .badge-inner.on-sale"],
                  "width:auto!important;height:auto!important;min-width:0!important;min-height:0!important"))
parts.append(rule(WOO, [".product-small .badge-inner.on-sale"],
                  "background:#1b1a18!important;border-radius:999px!important;padding:5px 10px!important;box-shadow:none!important;display:inline-flex!important;align-items:center!important"))
parts.append(rule(WOO, [".product-small .badge-inner.on-sale .onsale"],
                  "background:transparent!important;color:#faf9f6!important;padding:0!important;border-radius:0!important;font-size:10px!important;letter-spacing:.1em!important;text-transform:uppercase!important;font-weight:700!important;line-height:1!important"))
# —— 去掉悬浮快速加购/放大按钮的杂乱 ——
parts.append(rule(WOO, [".product-small .image-tools", ".product-small .add-to-cart-button", ".product-small .quick-view", ".product-small .wishlist-button"],
                  "display:none!important"))
# —— 网格间距舒展 ——
parts.append(rule(WOO, [".products .product-small"], "margin-bottom:clamp(28px,4vw,52px)!important"))
# —— 桌面改 4 列(卡片小一圈，一屏看更多)；移动端不动仍 2 列 ——
parts.append(
  "@media (min-width:850px){"
  "body.woocommerce-shop .products > .product-small,"
  "body.tax-product_cat .products > .product-small{"
  "width:25%!important;flex-basis:25%!important;max-width:25%!important}}"
)

# ============================ 详情页 PDP(单品页 · 全站模板级)============================
SP = ["body.single-product"]
# 页面底色
parts.append(rule(SP, ["#content"], "background:#f4f4f6!important"))
# —— 画廊:白瓷砖圆角 + 柔投影 ——
parts.append(rule(SP, [".product-gallery .woocommerce-product-gallery"],
    "background:#fff!important;border-radius:22px!important;overflow:hidden!important;box-shadow:0 1px 2px rgba(20,20,30,.04),0 24px 60px -30px rgba(20,20,30,.2)!important;padding:24px!important"))
# 画廊 Sale 角标 → 深色小胶囊
parts.append(rule(SP, [".badge-container .badge-inner.on-sale"],
    "background:#1b1a18!important;border-radius:999px!important;width:auto!important;height:auto!important;min-width:0!important;min-height:0!important;padding:5px 11px!important;display:inline-flex!important;align-items:center!important"))
parts.append(rule(SP, [".badge-container .badge-inner.on-sale .onsale"],
    "background:transparent!important;color:#faf9f6!important;font-size:10px!important;letter-spacing:.1em!important;text-transform:uppercase!important;font-weight:700!important;padding:0!important;line-height:1!important"))
# —— 买盒排版:撑满右半区(修右侧大片空白)——
parts.append(rule(SP, [".product-info.summary"], "flex:1 1 0!important;max-width:540px!important;padding-left:clamp(20px,3vw,48px)!important"))
parts.append(rule(SP, [".product-gallery.large-6"], "flex:0 0 52%!important;max-width:52%!important"))
parts.append(rule(SP, [".product_title"],
    "font-family:-apple-system,system-ui,'Segoe UI',sans-serif!important;font-size:30px!important;font-weight:600!important;letter-spacing:-.02em!important;line-height:1.15!important;color:#1b1a18!important;margin-bottom:12px!important"))
# 价格
parts.append(rule(SP, [".price.product-page-price .amount", ".price.product-page-price ins .amount"], "color:#1b1a18!important;font-weight:700!important"))
parts.append(rule(SP, [".price.product-page-price del .amount"], "color:#a49f98!important;font-weight:400!important;font-size:.8em!important"))
parts.append(rule(SP, [".price.product-page-price ins"], "text-decoration:none!important"))
# 短描述 = 价值主张
parts.append(rule(SP, [".product-short-description", ".product-short-description p"], "color:#6f6b66!important;font-size:15px!important;line-height:1.6!important"))
# 数量器
parts.append(rule(SP, [".ux-quantity.quantity"], "border:1px solid #d9d7d3!important;border-radius:12px!important;overflow:hidden!important;height:52px!important"))
parts.append(rule(SP, [".ux-quantity .quantity-button"], "background:#fff!important;color:#6f6b66!important;border:0!important"))
# 加入购物车表单:qty + 深色大按钮成排
parts.append(rule(SP, ["form.cart"], "display:flex!important;gap:12px!important;align-items:stretch!important;margin-bottom:8px!important"))
parts.append(rule(SP, [".single_add_to_cart_button"],
    "flex:1!important;background:#1b1a18!important;color:#fff!important;border:0!important;border-radius:12px!important;height:52px!important;font-size:15px!important;font-weight:600!important;letter-spacing:.02em!important;box-shadow:none!important;text-shadow:none!important;transition:transform .2s,background .2s!important"))
parts.append(rule(SP, [".single_add_to_cart_button:hover"], "background:#000!important;transform:translateY(-1px)!important"))
# 信任条(纯 CSS ::after 注入,全站单品页;先用绝对成立的安全项,W-S 真实政策定了再换具体承诺)
parts.append("body.single-product form.cart{flex-wrap:wrap!important}")
parts.append('body.single-product form.cart::after{content:"\\2713 Secure checkout\\00a0\\00a0\\00b7\\00a0\\00a0 \\2713 30-day quality guarantee\\00a0\\00a0\\00b7\\00a0\\00a0 \\2713 Worldwide tracked shipping";flex-basis:100%!important;order:9!important;margin-top:18px!important;padding-top:16px!important;border-top:1px solid #e7e6e3!important;font-size:12.5px!important;color:#6f6b66!important;line-height:1.7!important}')
# 杀掉丑社交分享图标
parts.append(rule(SP, [".share-icons", ".social-icons.share-row", ".product_meta .sku_wrapper"], "display:none!important"))
# 类目 meta 行:低调分隔
parts.append(rule(SP, [".product_meta"], "border-top:1px solid #e7e6e3!important;margin-top:22px!important;padding-top:18px!important;font-size:12.5px!important;letter-spacing:.02em!important;color:#a49f98!important"))
parts.append(rule(SP, [".product_meta .posted_in a"], "color:#6f6b66!important"))
# —— 标签页(描述/FAQ/评价):干净 ——
parts.append(rule(SP, [".woocommerce-tabs"], "background:#fff!important;border-radius:22px!important;padding:clamp(24px,3vw,44px)!important;margin-top:30px!important;box-shadow:0 1px 2px rgba(20,20,30,.04),0 20px 50px -34px rgba(20,20,30,.16)!important"))
parts.append(rule(SP, [".woocommerce-tabs ul.tabs"], "border:0!important;margin:0 0 22px!important;padding:0!important"))
parts.append(rule(SP, [".woocommerce-tabs ul.tabs li"], "border:0!important;background:transparent!important;margin:0 22px 0 0!important;padding:0!important"))
parts.append(rule(SP, [".woocommerce-tabs ul.tabs li a"], "font-size:12.5px!important;letter-spacing:.12em!important;text-transform:uppercase!important;font-weight:700!important;color:#a49f98!important;padding:0 0 8px!important;border-bottom:2px solid transparent!important"))
parts.append(rule(SP, [".woocommerce-tabs ul.tabs li.active a"], "color:#1b1a18!important;border-bottom-color:#1b1a18!important"))
parts.append(rule(SP, [".woocommerce-Tabs-panel", ".woocommerce-tabs .panel"], "color:#4a4844!important;font-size:15px!important;line-height:1.7!important"))
# —— 评价区:去掉难看的登录大框,精致化 ——
parts.append(rule(SP, ["#review_form_wrapper", ".comment-respond"], "background:#faf9f6!important;border:1px solid #e7e6e3!important;border-radius:14px!important;padding:20px 22px!important"))
parts.append(rule(SP, [".woocommerce-noreviews"], "color:#6f6b66!important;font-size:14.5px!important"))
# —— 相关产品沿用店面家规卡片(已有 body.woocommerce .product-small 规则),这里只保证标题风格 ——
parts.append(rule(SP, [".related.products>h2", ".up-sells>h2"], "text-align:center!important;font-size:13px!important;letter-spacing:.16em!important;text-transform:uppercase!important;color:#a49f98!important;font-weight:700!important;margin-bottom:34px!important"))

# ===================== 详情页描述区(.kp-*)家规化,覆盖 Customizer 彩色 CSS =====================
D = "body.single-product .kp-desc"
parts.append(f"{D}{{max-width:940px!important;margin:0 auto!important;color:#4a4844!important;font-size:15.5px!important;line-height:1.75!important}}")
# 大标题/引言
parts.append(f"{D} .kp-headline{{font-family:-apple-system,system-ui,'Segoe UI',sans-serif!important;font-size:clamp(24px,3vw,32px)!important;font-weight:600!important;letter-spacing:-.02em!important;color:#1b1a18!important;text-align:center!important;margin:10px 0 6px!important}}")
parts.append(f"{D} .kp-subheadline{{text-align:center!important;color:#6f6b66!important;font-size:16px!important;margin:0 0 8px!important}}")
parts.append(f"{D} .kp-lead{{text-align:center!important;color:#6f6b66!important;max-width:62ch!important;margin:0 auto 8px!important}}")
parts.append(f"{D} h3,{D} section h2,{D} .kp-module-text h2,{D} .kp-specs h2,{D} .kp-faq h2{{font-size:20px!important;font-weight:600!important;letter-spacing:-.01em!important;color:#1b1a18!important;margin:8px 0 8px!important;text-align:left!important}}")
# 卖点:杀绿豆底 + 深色极简勾
parts.append(f"{D} .kp-benefits ul{{gap:12px 26px!important}}")
parts.append(f"{D} .kp-benefits li{{background:transparent!important;border:0!important;border-bottom:1px solid #ececea!important;border-radius:0!important;padding:11px 0 11px 26px!important;color:#2b2a28!important;font-size:15px!important;position:relative!important}}")
parts.append(f'{D} .kp-benefits li::before{{content:"\\2713"!important;color:#1b1a18!important;background:none!important;background-image:none!important;background-color:transparent!important;border:0!important;border-radius:0!important;width:auto!important;height:auto!important;font-size:13px!important;font-weight:700!important;line-height:1!important;position:absolute!important;left:0!important;top:13px!important}}')
# 图片:限高 + 家规瓷砖(治 860px 过高)
parts.append(f"{D} .kp-figure{{margin:22px auto!important;text-align:center!important}}")
parts.append(f"{D} .kp-figure img{{max-height:400px!important;width:auto!important;max-width:100%!important;border-radius:16px!important;background:#fff!important;box-shadow:0 1px 2px rgba(20,20,30,.04),0 16px 40px -22px rgba(20,20,30,.18)!important;margin:0 auto!important}}")
parts.append(f"{D} .kp-figure figcaption{{color:#a49f98!important;font-size:12.5px!important;margin-top:9px!important;text-align:center!important}}")
# 图文并排模块(新模板会包 .kp-module;老结构不含则不影响)
parts.append(f"{D} .kp-module{{display:grid!important;grid-template-columns:1fr 1fr!important;gap:clamp(20px,3vw,44px)!important;align-items:center!important;margin:34px 0!important}}")
parts.append(f"{D} .kp-module .kp-figure{{margin:0!important}}")
parts.append(f"{D} .kp-module.rev .kp-figure{{order:-1!important}}")
parts.append(f"{D} .kp-module .kp-figure img{{max-height:340px!important;width:100%!important;object-fit:cover!important;aspect-ratio:4/3!important}}")

parts.append("@media(max-width:760px){body.single-product .kp-desc .kp-module{grid-template-columns:1fr!important}body.single-product .kp-desc .kp-module .kp-figure{order:0!important}}")
# 规格表:家规清爽
parts.append(f"{D} .kp-specs{{background:#faf9f6!important;border:1px solid #ececea!important;border-radius:16px!important;padding:8px 22px!important;margin:30px 0!important}}")
parts.append(f"{D} .kp-specs table{{width:100%!important}}")
parts.append(f"{D} .kp-specs th,{D} .kp-specs td{{padding:12px 4px!important;border-bottom:1px solid #ececea!important;font-size:14.5px!important;text-align:left!important}}")
parts.append(f"{D} .kp-specs th{{color:#6f6b66!important;font-weight:500!important}}")
# 信任块:低调 aside
parts.append(f"{D} .kp-trust{{background:#faf9f6!important;border-left:3px solid #1b1a18!important;border-radius:8px!important;padding:16px 20px!important;color:#4a4844!important;font-size:14.5px!important;margin:26px 0!important}}")
# FAQ 手风琴:家规
parts.append(f"{D} .kp-faq details{{border-bottom:1px solid #ececea!important;background:transparent!important;padding:0!important}}")
parts.append(f"{D} .kp-faq summary{{padding:16px 0!important;font-size:15.5px!important;font-weight:500!important;color:#1b1a18!important;cursor:pointer!important;list-style:none!important}}")
parts.append(f"{D} .kp-faq .kp-faq-a{{color:#6f6b66!important;padding:0 0 16px!important;font-size:14.5px!important}}")

# ============ 404 品牌页(文案与按钮由 barong-redirects 插件注入)============
E4 = "body.error404"
parts.append(f"{E4} .error-404 .row{{display:block!important;max-width:660px!important;margin:0 auto!important;text-align:center!important;padding:clamp(28px,6vw,72px) 18px!important}}")
parts.append(f"{E4} .error-404 .col{{max-width:100%!important;flex-basis:100%!important;padding:0!important}}")
# 主题那个巨大的半透明 "404" → 收成克制的小眉标
parts.append(f"{E4} .error-404 .col.medium-3 span.header-font{{font-size:11.5px!important;font-weight:700!important;letter-spacing:.22em!important;opacity:1!important;color:#a49f98!important;display:block!important;margin:0 0 16px!important}}")
parts.append(f"{E4} .error-404 h1.page-title{{font-size:clamp(28px,4.4vw,42px)!important;letter-spacing:-.02em!important;color:#1b1a18!important;margin:0 0 14px!important}}")
parts.append(f"{E4} .error-404 header.page-title{{border:0!important;padding:0!important;background:transparent!important}}")
parts.append(f"{E4} .error-404 .page-content p{{font-size:16.5px!important;line-height:1.7!important;color:#3d3a36!important;max-width:520px!important;margin:0 auto 26px!important}}")
parts.append(f"{E4} .error-404 .searchform{{max-width:420px!important;margin:0 auto!important}}")
parts.append(f"{E4} .by-404-cta{{display:flex;gap:12px;justify-content:center;flex-wrap:wrap;margin-top:28px}}")
parts.append(f"{E4} .by-404-btn{{background:#1b1a18!important;color:#faf9f6!important;border:1px solid #1b1a18!important;border-radius:999px!important;padding:13px 28px!important;font-weight:600!important;font-size:14.5px!important;text-decoration:none!important;display:inline-block!important;transition:opacity .2s ease}}")
parts.append(f"{E4} .by-404-btn.ghost{{background:transparent!important;color:#1b1a18!important;border:1px solid #d9d7d3!important}}")
parts.append(f"{E4} .by-404-btn:hover{{opacity:.86!important}}")

CSS = "".join(parts)
open("shop_house.css", "w").write(CSS)
# 安全自检：确保没有任何裸 body 简单选择器后面直接跟 { (会命中整个 body)
import re
bad = re.findall(r'(?:^|,)\s*body\.[a-z-]+\s*\{', CSS)
print("shop 家规 CSS:", len(CSS), "字节 | 危险裸body规则数(应为0):", len(bad))
if bad:
    print("!! 危险:", bad)
