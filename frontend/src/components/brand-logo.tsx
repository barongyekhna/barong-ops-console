export const BRAND_LOGO_SRC = "/assets/brand/barong-logo.svg";

type BrandLogoProps = {
  alt?: string;
  className?: string;
  decorative?: boolean;
};

export function BrandLogo({
  alt = "Barong logo",
  className = "",
  decorative = false,
}: BrandLogoProps) {
  return (
    <img
      alt={decorative ? "" : alt}
      aria-hidden={decorative ? "true" : undefined}
      className={`brand-logo-image ${className}`.trim()}
      draggable={false}
      src={BRAND_LOGO_SRC}
    />
  );
}

export function Logo(props: BrandLogoProps) {
  return <BrandLogo {...props} />;
}
