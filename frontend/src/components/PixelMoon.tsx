// PixelMoon — the Eepy mascot: a sleepy 16-bit moon with closed eyes,
// blush cheeks, and a warm top-left shine. Rendered as crisp SVG rects
// (shapeRendering: crispEdges) so it stays sharp at any size.

const MOON_MAP = [
  '......CCCC......',
  '....CCCCCCCC....',
  '...CCHHCCCCCC...',
  '..CCHCCCCCCCCC..',
  '..CCKKCCCCKKCC..',
  '..CCBBCCCCBBCC..',
  '.CCCCCCKKCCCCCC.',
  '.CCCCCCCCCCCCCC.',
  '..CCCCCCCCCCCC..',
  '..CCCCCCCCCCSS..',
  '...CCCCCCCCSS...',
  '....CCCCCCSS....',
  '......CCSS......',
  '.......CC.......',
];

const MOON_COLORS: Record<string, string> = {
  C: '#F6E7D3', // cream body
  H: '#FFF7EA', // warm shine
  K: '#5A3A4A', // sleepy eyes / mouth
  B: '#F2A3B0', // blush
  S: '#E3C9AC', // soft shade
};

interface Props {
  size?: number;
  className?: string;
}

export default function PixelMoon({ size = 64, className }: Props) {
  const w = 16;
  const h = MOON_MAP.length;
  const rects: React.ReactNode[] = [];
  MOON_MAP.forEach((row, y) => {
    for (let x = 0; x < w; x++) {
      const color = MOON_COLORS[row[x]];
      if (!color) continue;
      rects.push(<rect key={`${x}-${y}`} x={x} y={y} width={1.02} height={1.02} fill={color} />);
    }
  });
  return (
    <svg
      width={size}
      height={(size / w) * h}
      viewBox={`0 0 ${w} ${h}`}
      shapeRendering="crispEdges"
      className={className}
      role="img"
      aria-label="Sleepy pixel moon"
    >
      {rects}
    </svg>
  );
}
