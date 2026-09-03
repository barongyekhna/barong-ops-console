// 让 node 能解析前端源码里的 `@/` 路径别名。
//
// 前端测试跑的是 `node --test tests/frontend/*.test.mjs`,没有 webpack/Next
// 那套别名解析,所以任何 import 了 `@/lib/...` 的模块都 import 不进来 ——
// 这就是为什么在这之前**没有一条测试真的调用过 `apiRequest`**,
// 关于它的断言全是「读源码文本匹配正则」。
//
// 路径从本文件自身的位置推导,不从 process.cwd() 推 —— 前端构建容器里的
// 目录布局和仓库根目录不一样,靠 cwd 会在容器里悄悄解析到别处。
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const srcDir = pathToFileURL(path.resolve(here, "../../frontend/src") + "/").href;

// `@/lib/request-cache` 在源码里不带扩展名(Next 的解析器会补),node ESM 不会,
// 所以这里按 TS 项目的惯例逐个试。顺序和 tsconfig 的 moduleResolution 一致。
const CANDIDATES = ["", ".ts", ".tsx", "/index.ts", "/index.tsx"];

async function tryCandidates(base, context, nextResolve) {
  let lastError;
  for (const suffix of CANDIDATES) {
    try {
      return await nextResolve(base + suffix, context);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith("@/")) {
    return tryCandidates(srcDir + specifier.slice(2), context, nextResolve);
  }
  // 相对导入同理：源码里写的是 `./publish-gate-error`，Next 的解析器会补
  // 扩展名，node ESM 不会。只在原样解析失败时才补 —— 正常能解析的一律不碰。
  if (specifier.startsWith("./") || specifier.startsWith("../")) {
    try {
      return await nextResolve(specifier, context);
    } catch {
      return tryCandidates(specifier, context, nextResolve);
    }
  }
  return nextResolve(specifier, context);
}
