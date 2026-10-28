import type { Product } from "../api";

// Neutral packaging drawings by role. Brand names are the catalog's fictional ones;
// no real trademark ever appears.
type Shape = "tube" | "dropper" | "jar" | "mist";
const SHAPE: Record<Product["role"], Shape> = {
  cleanser: "tube",
  treatment: "tube",
  sunscreen: "tube",
  serum: "dropper",
  moisturiser: "jar",
  toner: "mist",
};

const BODY = "#FBF9F5";
const EDGE = "#D9D2C6";
const CAP = "#E4DDD1";
const INK = "#6B655C";

// Up to two balanced lines, sized so the widest line fits the label area.
function Label({ text, y, width }: { text: string; y: number; width: number }) {
  const words = text.split(/\s+/).filter(Boolean);
  let lines = [text];
  if (words.length > 1) {
    let best = [text];
    let bestMax = Infinity;
    for (let i = 1; i < words.length; i++) {
      const a = words.slice(0, i).join(" ");
      const b = words.slice(i).join(" ");
      const m = Math.max(a.length, b.length);
      if (m < bestMax) {
        bestMax = m;
        best = [a, b];
      }
    }
    lines = best;
  }
  const ls = 0.6;
  const longest = Math.max(...lines.map((l) => l.length));
  const fs = Math.max(4, Math.min(8, (width / longest - ls) / 0.64));
  const top = y - ((lines.length - 1) * fs * 1.25) / 2;
  return (
    <text textAnchor="middle" fontSize={fs.toFixed(2)} letterSpacing={ls} fill={INK} fontFamily="Inter Variable, Inter, sans-serif">
      {lines.map((l, i) => (
        <tspan key={i} x="60" y={(top + i * fs * 1.25).toFixed(2)}>
          {l}
        </tspan>
      ))}
    </text>
  );
}

export function ProductArt({ product, size = 64 }: { product: Pick<Product, "role" | "brand" | "name">; size?: number }) {
  const shape = SHAPE[product.role] ?? "tube";
  const brand = product.brand.toUpperCase();
  return (
    <svg
      className="productart"
      width={size}
      height={(size * 4) / 3}
      viewBox="0 0 120 160"
      role="img"
      aria-label={`${product.name} by ${product.brand} (illustration)`}
    >
      {shape === "tube" && (
        <g>
          <path d="M34 22h52l-6 118a8 8 0 0 1-8 7.5H48a8 8 0 0 1-8-7.5z" fill={BODY} stroke={EDGE} strokeWidth="1.5" />
          <rect x="30" y="10" width="60" height="14" rx="2" fill={CAP} stroke={EDGE} strokeWidth="1.5" />
          {[38, 46, 54, 62, 70, 78].map((x) => (
            <line key={x} x1={x} y1="12" x2={x} y2="22" stroke={EDGE} strokeWidth="1" />
          ))}
          <Label text={brand} y={92} width={38} />
        </g>
      )}
      {shape === "dropper" && (
        <g>
          <rect x="52" y="6" width="16" height="20" rx="8" fill={CAP} stroke={EDGE} strokeWidth="1.5" />
          <rect x="47" y="24" width="26" height="18" rx="3" fill={CAP} stroke={EDGE} strokeWidth="1.5" />
          <path d="M40 48a8 8 0 0 1 8-6h24a8 8 0 0 1 8 6v90a10 10 0 0 1-10 10H50a10 10 0 0 1-10-10z" fill={BODY} stroke={EDGE} strokeWidth="1.5" />
          <Label text={brand} y={100} width={28} />
        </g>
      )}
      {shape === "jar" && (
        <g>
          <rect x="22" y="58" width="76" height="22" rx="4" fill={CAP} stroke={EDGE} strokeWidth="1.5" />
          <path d="M24 80h72v52a12 12 0 0 1-12 12H36a12 12 0 0 1-12-12z" fill={BODY} stroke={EDGE} strokeWidth="1.5" />
          <Label text={brand} y={116} width={64} />
        </g>
      )}
      {shape === "mist" && (
        <g>
          <rect x="54" y="8" width="12" height="10" rx="2" fill={CAP} stroke={EDGE} strokeWidth="1.5" />
          <rect x="48" y="18" width="24" height="20" rx="4" fill={CAP} stroke={EDGE} strokeWidth="1.5" />
          <path d="M44 38h32v104a8 8 0 0 1-8 8H52a8 8 0 0 1-8-8z" fill={BODY} stroke={EDGE} strokeWidth="1.5" />
          <Label text={brand} y={98} width={26} />
        </g>
      )}
    </svg>
  );
}
