export default function CsCommandLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="ra-command cs-command">
      <div className="ra-command-space" aria-hidden>
        <div className="ra-command-nebula" />
        <div className="ra-command-phoenix" />
      </div>
      <div className="ra-command-content">{children}</div>
    </div>
  );
}
