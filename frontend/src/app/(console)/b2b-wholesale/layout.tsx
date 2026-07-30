export default function B2BCommandLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // 复用现有 .ra-command 火凤凰驾驶舱皮肤，不覆盖全局驾驶舱样式。
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
