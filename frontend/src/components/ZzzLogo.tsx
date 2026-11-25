// ZzzLogo — the Eepy zzz mark (the favicon, frontend/public/favicon.png),
// the small in-UI brand mark. Plain <img> with pixelated rendering: the
// favicon IS the pixel art, so an optimizer would only soften it.
// Same prop shape as the old PixelMoon (size + className).

interface Props {
  size?: number;
  className?: string;
}

export default function ZzzLogo({ size = 64, className }: Props) {
  return (
    <img
      src="/favicon.png"
      alt="Eepy zzz"
      width={size}
      height={size}
      className={className}
      style={{ imageRendering: 'pixelated' }}
    />
  );
}
