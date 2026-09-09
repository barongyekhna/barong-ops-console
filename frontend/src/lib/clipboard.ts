/**
 * 一键复制。先走 navigator.clipboard,不行(http 页面 / 老浏览器 / 权限被拒)就退回
 * 隐藏输入框 + execCommand。两条路都失败返回 false,调用方自己决定怎么兜底。
 *
 * 从 modules/r/analysis/AnalysisWorkspace.tsx 抽出来的:全站以前每处各写一份。
 */
export async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard?.writeText(value);
    return true;
  } catch {
    return fallbackCopyText(value);
  }
}

export function fallbackCopyText(value: string): boolean {
  if (typeof document === "undefined") {
    return false;
  }
  const input = document.createElement("input");
  input.value = value;
  input.setAttribute("readonly", "true");
  input.style.position = "fixed";
  input.style.left = "0";
  input.style.top = "0";
  input.style.width = "1px";
  input.style.height = "1px";
  input.style.opacity = "0";
  input.style.pointerEvents = "none";
  document.body.appendChild(input);
  input.focus({ preventScroll: true });
  input.select();
  input.setSelectionRange(0, input.value.length);
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(input);
  }
}
