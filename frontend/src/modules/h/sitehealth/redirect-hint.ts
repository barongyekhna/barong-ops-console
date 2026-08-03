/**
 * 死链 →「设跳转」的三个纯函数。
 *
 * 抽出来单独放，是因为 HealthDeck（判断该不该给这条死链显示按钮）和
 * RedirectManager（把路径填进跳转表、给个推荐目标）都要用同一套判断，
 * 抄两份必然分叉。
 */

/**
 * 独立站主域名。跳转表由站上的 barong-redirects 插件执行，**它只在本站 404 时生效**，
 * 所以站外死链给不了跳转（给个按钮反而误导人）。
 * 写死是有意的：哨兵那边巡检目标同样写死（执行面自己知道站是哪个，控制台不传）。
 */
export const SITE_HOST = "barongyekhna.com";

/** 这条死链是不是本站的——只有本站的才谈得上设跳转。 */
export function isInternalUrl(url: string): boolean {
  const match = /^https?:\/\/([^/?#]+)/i.exec(String(url ?? ""));
  if (!match) return false;
  return match[1].toLowerCase().replace(/^www\./, "") === SITE_HOST;
}

/**
 * URL → 跳转表的键。
 *
 * ⚠️ 必须和插件里的 `by_rd_normalize` 对齐：**小写、去尾斜杠、空路径归一为 "/"**。
 * 对不齐的话表里写了也匹配不上，页面照样 404 —— 而且这种错不会报错，只会静默不生效。
 * 查询串要保留：跳转表里已有 `/?page_id=1759` 这种键，插件两种形式都能匹配。
 */
export function toRedirectPath(url: string): string | null {
  const raw = String(url ?? "").trim();
  if (!raw) return null;
  const match = /^https?:\/\/[^/?#]+(.*)$/i.exec(raw);
  // 允许直接传路径（跳转表里存的就是路径形式）
  let rest = match ? match[1] : raw.startsWith("/") ? raw : null;
  if (rest === null) return null;
  rest = rest.split("#")[0].toLowerCase();
  if (!rest) return "/";
  const trimmed = rest.replace(/\/+$/, "");
  return trimmed === "" ? "/" : trimmed;
}

/**
 * 按路径规律给个**推荐**目标——只是省去打字，最终跳哪儿由人确认。
 *
 * 依据是站上已有的那批跳转：下架产品和类目一律回商店。
 * 刻意不做得更聪明：「跳到哪」是生意判断不是数据推导，
 * 比如已下架的冷疗仪就该跳它的**说明书页**（买过的老客户还要看），
 * 这种事系统猜不出来，猜错了人还不知道。
 */
export function suggestRedirectTarget(path: string): string {
  const p = toRedirectPath(path) ?? "/";
  if (p.startsWith("/product-category/") || p.startsWith("/product/")) {
    return "/shop-2/";
  }
  return "/";
}
