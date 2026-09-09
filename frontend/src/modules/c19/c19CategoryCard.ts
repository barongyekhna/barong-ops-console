/**
 * 数字员工殷承岳的「类目卡」文本格式解析。
 *
 * C19 的记录服务只认 text/emoji/image/file,所以卡片仍是一条文本:
 * 首行 `【类目 #a1b2】Camping Cookware`,末行机器标记 `⟦category:a1b2⟧`,中间是
 * `路径：` / `中文：` / `原因：` / `备选：` / `置信：` 几行。前端认出标记就渲染成带
 * 复制按钮的卡片;别的客户端看到的还是可读文本,英文类目名就在首行。
 * 语法与 backend/app/modules/agent_series/yinchengyue/reply.py 一一对应。
 */

const CARD_HEAD = /^【类目 #([0-9a-f]{4})】(.+)$/;
const CARD_MARKER = /^⟦category:([0-9a-f]{4})⟧$/;
// 冒号接受全角和半角,免得哪天文案改了一个字符就整张卡退化成纯文本。
const FIELD = /^(路径|中文|原因|备选|置信)[：:]\s*(.*)$/;
const ALT_SEPARATOR = /\s+[—–-]{1,2}\s+/;

export type ParsedCategoryCard = {
  cardId: string;
  /** 英文类目名(叶子),就是要一键复制的那个。 */
  leafName: string;
  path: string[];
  nameZh: string;
  reason: string;
  alternates: { name: string; reason: string }[];
  confidence: string;
  /** 卡片前面的一句话(目前没有,留着和待确认卡对齐)。 */
  preface: string;
};

export function parseC19CategoryCard(
  content: string | null | undefined,
): ParsedCategoryCard | null {
  if (!content) return null;
  const lines = content.split("\n");
  if (lines.length < 2) return null;
  const marker = CARD_MARKER.exec(lines[lines.length - 1].trim());
  if (!marker) return null;
  const headIndex = lines.findIndex((line) => CARD_HEAD.test(line.trim()));
  if (headIndex < 0) return null;
  const head = CARD_HEAD.exec(lines[headIndex].trim());
  if (!head || head[1] !== marker[1]) return null;

  const card: ParsedCategoryCard = {
    cardId: head[1],
    leafName: head[2].trim(),
    path: [],
    nameZh: "",
    reason: "",
    alternates: [],
    confidence: "",
    preface: lines.slice(0, headIndex).join("\n").trim(),
  };
  if (!card.leafName) return null;

  for (const raw of lines.slice(headIndex + 1, -1)) {
    const line = raw.trim();
    if (!line) continue;
    const field = FIELD.exec(line);
    if (!field) {
      // 原因可能被换行成多行:接到上一段原因后面。
      if (card.reason) card.reason = `${card.reason} ${line}`;
      continue;
    }
    const value = field[2].trim();
    switch (field[1]) {
      case "路径":
        card.path = value
          .split(/\s*>\s*/)
          .map((part) => part.trim())
          .filter(Boolean);
        break;
      case "中文":
        card.nameZh = value === "—" ? "" : value;
        break;
      case "原因":
        card.reason = value;
        break;
      case "备选": {
        const [name, ...rest] = value.split(ALT_SEPARATOR);
        if (name?.trim()) {
          card.alternates.push({ name: name.trim(), reason: rest.join(" ").trim() });
        }
        break;
      }
      case "置信":
        card.confidence = value;
        break;
      default:
        break;
    }
  }
  return card;
}
