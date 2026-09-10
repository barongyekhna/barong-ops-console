export default function MfgCostLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // 复用 .ra-command 驾驶舱皮肤，与库存页一致。
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
