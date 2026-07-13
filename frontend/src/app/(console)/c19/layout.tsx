export default function C19CommandLayout({
  children,
}: {
  children: React.ReactNode;
}) {
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
