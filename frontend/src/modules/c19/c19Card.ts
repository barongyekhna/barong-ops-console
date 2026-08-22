/**
 * 数字员工「待确认卡」的文本格式解析。
 *
 * C19 的记录服务只认 text/emoji/image/file,所以卡片仍是一条文本:
 * 某行 `【待确认 #ab12】入库`,末行机器标记 `⟦card:ab12⟧`;前面可以带一句前言。
 * 前端认出标记就渲染成带「确认 / 取消」按钮的卡片。
 */

const CARD_HEAD = /^【待确认 #([0-9a-f]{4})】(.*)$/;
const CARD_MARKER = /^⟦card:([0-9a-f]{4})⟧$/;

export type ParsedCard = {
  cardId: string;
  title: string;
  lines: string[];
  /** 卡片前面的一句话,如「上一张卡 #5809 已作废。」 */
  preface: string;
};

export function parseC19Card(content: string | null | undefined): ParsedCard | null {
  if (!content) return null;
  const lines = content.split("\n");
  if (lines.length < 2) return null;
  const marker = CARD_MARKER.exec(lines[lines.length - 1].trim());
  if (!marker) return null;
  const headIndex = lines.findIndex((line) => CARD_HEAD.test(line.trim()));
  if (headIndex < 0) return null;
  const head = CARD_HEAD.exec(lines[headIndex].trim());
  if (!head || head[1] !== marker[1]) return null;
  const body = lines
    .slice(headIndex + 1, -1)
    .filter((line) => !line.trim().startsWith("回「确认」"))
    .map((line) => line.replace(/^\s{2}/, ""));
  return {
    cardId: head[1],
    title: head[2].trim(),
    lines: body,
    preface: lines.slice(0, headIndex).join("\n").trim(),
  };
}

