export default function PCommandLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // 复用 .ra-command 火凤凰驾驶舱皮肤（globals.css 同一视觉体系）
  return (
    <div className="ra-command">
      <div className="ra-command-space" aria-hidden>
        <div className="ra-command-nebula" />
        <div className="ra-command-phoenix" />
      </div>
      <div className="ra-command-content">{children}</div>
    </div>
  );
}
