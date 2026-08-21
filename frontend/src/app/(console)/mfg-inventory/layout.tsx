export default function MfgInventoryLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // 复用 .ra-command 驾驶舱皮肤，不覆盖全局样式。
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
