"use client";

import styles from "./ContentDesk.module.css";
import type { Article } from "./types";

/**
 * 一套渲染吃两种正文。
 *
 * GEO 的 body 有 sections + answer_blocks 两种块，SEO 只有 sections。归一化层
 * 已经保证两个键**恒存在**（SEO 的 answer_blocks 是 []），所以这里不需要
 * 判断来源，空数组自然什么都不渲染。
 */
export function ArticleBody({ article }: { article: Article }) {
  const { sections, answer_blocks: answers } = article.body;
  if (!sections.length && !answers.length) {
    return <p className={styles.empty}>这篇还没有正文。</p>;
  }
  return (
    <div>
      {sections.map((section, index) => (
        <div key={`s-${index}`}>
          {section.heading ? (
            <h4 className={styles.articleHeading}>{section.heading}</h4>
          ) : null}
          {section.body ? (
            <p className={styles.articleBody}>{section.body}</p>
          ) : null}
        </div>
      ))}
      {answers.length ? (
        <div className={styles.blockLabel}>买家问答</div>
      ) : null}
      {answers.map((block, index) => (
        <div key={`a-${index}`}>
          {block.question ? (
            <div className={styles.question}>{block.question}</div>
          ) : null}
          {block.answer ? (
            <p className={styles.articleBody}>{block.answer}</p>
          ) : null}
        </div>
      ))}
    </div>
  );
}
