/**
 * M 系列「出货明细卡」的文本格式解析。
 *
 * C19 的记录服务只认 text/emoji/image/file（消息在独立部署的 c19_record_service
 * 里，加一种 content_type 要跨两个服务、两套迁移），所以卡片仍是一条文本：
 * 首行 `【出货明细 #a1b2】折叠桌 TBL-001 × 100 套`，末行机器标记 `⟦cost:a1b2⟧`，
 * 中间是 `单号：` / `批量：` / `料|…` / `工|…` / `计：` / `价：` / `效：` 几种行。
 * 前端认出标记就渲染成表格；别的客户端、通知摘要、以后翻聊天记录的人，看到的都
 * 还是一段能读懂的文本。
 *
 * 语法与 backend/app/modules/m_series/cost/card.py 一一对应，改一边必须改另一边。
 */

const CARD_HEAD = /^【出货明细 #([0-9a-f]{4})】(.+)$/;
const CARD_MARKER = /^⟦cost:([0-9a-f]{4})⟧$/;
// 冒号接受全角和半角，免得哪天文案改了一个字符就整张卡退化成纯文本。
const FIELD = /^(单号|批量|计|价|效|缺价)[：:]\s*(.*)$/;

export type CostCardMaterial = {
  code: string;
  name: string;
  qty: string;
  unitPrice: string;
  unitFreight: string;
  lineTotal: string;
};

export type CostCardLabor = {
  name: string;
  mode: string;
  rate: string;
  lineTotal: string;
};

export type ParsedCostCard = {
  cardId: string;
  title: string;
  sheetNo: string;
  batch: string;
  materials: CostCardMaterial[];
  labor: CostCardLabor[];
  totals: string;
  price: string;
  expires: string;
  shortage: string;
  /** 仅出厂价口径：整张卡里根本没有成本行。 */
  priceOnly: boolean;
  preface: string;
};

export function parseC19CostCard(
  content: string | null | undefined,
): ParsedCostCard | null {
  if (!content) return null;
  const lines = content.split("\n");
  if (lines.length < 2) return null;
  const marker = CARD_MARKER.exec(lines[lines.length - 1].trim());
  if (!marker) return null;
  const headIndex = lines.findIndex((line) => CARD_HEAD.test(line.trim()));
  if (headIndex < 0) return null;
  const head = CARD_HEAD.exec(lines[headIndex].trim());
  if (!head || head[1] !== marker[1]) return null;

  const card: ParsedCostCard = {
    batch: "",
    cardId: head[1],
    expires: "",
    labor: [],
    materials: [],
    preface: lines.slice(0, headIndex).join("\n").trim(),
    price: "",
    priceOnly: true,
    sheetNo: "",
    shortage: "",
    title: head[2].trim(),
    totals: "",
  };
  if (!card.title) return null;

  for (const raw of lines.slice(headIndex + 1, -1)) {
    const line = raw.trim();
    if (!line) continue;

    if (line.startsWith("料|")) {
      const cells = line.split("|");
      card.materials.push({
        code: cells[1] ?? "",
        lineTotal: cells[6] ?? "",
        name: cells[2] ?? "",
        qty: cells[3] ?? "",
        unitFreight: cells[5] ?? "",
        unitPrice: cells[4] ?? "",
      });
      card.priceOnly = false;
      continue;
    }
    if (line.startsWith("工|")) {
      const cells = line.split("|");
      card.labor.push({
        lineTotal: cells[4] ?? "",
        mode: cells[2] ?? "",
        name: cells[1] ?? "",
        rate: cells[3] ?? "",
      });
      card.priceOnly = false;
      continue;
    }

    const field = FIELD.exec(line);
    if (!field) continue;
    const value = field[2].trim();
    switch (field[1]) {
      case "单号":
        card.sheetNo = value;
        break;
      case "批量":
        card.batch = value;
        break;
      case "计":
        card.totals = value;
        card.priceOnly = false;
        break;
      case "价":
        card.price = value;
        break;
      case "效":
        card.expires = value;
        break;
      case "缺价":
        card.shortage = value;
        break;
      default:
        break;
    }
  }
  return card;
}

/**
 * 报价过期了没有。
 *
 * `效：2026-09-18（含铜价类波动料）` —— 取前面那段日期。解析不出日期就当没过期，
 * 宁可不提示，也不要把一张好卡片错标成失效。
 */
export function isCostCardExpired(
  card: ParsedCostCard,
  now: Date = new Date(),
): boolean {
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(card.expires);
  if (!match) return false;
  const expiry = new Date(`${match[1]}T23:59:59`);
  if (Number.isNaN(expiry.getTime())) return false;
  return now > expiry;
}
