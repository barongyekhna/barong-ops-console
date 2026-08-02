"use client";

/**
 * 内容台。**它不是第三台引擎**——不生成内容、不发明状态，只把 GEO/SEO
 * 归一化成一页：现在卡在哪一步、该你做什么、机器有没有在跑。
 */
export function ContentDesk() {
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div
        style={{
          background: "#0d131bcc",
          border: "1px solid #ffffff1a",
          borderRadius: 10,
          color: "#8b98a8",
          fontSize: 13,
          padding: 18,
        }}
      >
        内容台正在搭建中。现在请继续用 GEO / SEO 两个引擎页面。
      </div>
    </div>
  );
}
