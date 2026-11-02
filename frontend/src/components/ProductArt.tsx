import type { Product } from "../api";

// Illustrated packs for the fictional catalogue: the shape comes from the product type, the colour
// from the (fictional) brand, and the label carries the product's own fictional name. Drawn here
// as SVG: no photos, nothing downloaded, no real trademark.
type Shape = "pump" | "dropper" | "jar" | "tube" | "slimtube" | "mist";
type Art = Pick<Product, "role" | "brand" | "name">;

function shapeOf({ role, name }: Art): Shape {
  const n = name.toLowerCase();
  if (role === "serum" || /essence|serum|shot/.test(n)) return "dropper";
  if (role === "toner" || /mist|toner/.test(n)) return "mist";
  if (/tint/.test(n)) return "slimtube";
  if (role === "cleanser" || /lotion/.test(n)) return "pump";
  if (/cream|balm|butter/.test(n)) return "jar";
  return "tube";
}

// One muted colour per brand, in the app's warm paper palette (no gradients).
const BRAND: Record<string, { cap: string; body: string; ink: string }> = {
  "Kora Labs": { cap: "#b9775a", body: "#ecd3c4", ink: "#5b3423" },
  Duneglow: { cap: "#c79a4f", body: "#f0dfbb", ink: "#5d4318" },
  "Nimbus Skin": { cap: "#7f97ab", body: "#d9e2ea", ink: "#2f4252" },
  Saltmint: { cap: "#78a08a", body: "#d6e6db", ink: "#2c4a39" },
  "Lumen & Leaf": { cap: "#8d8f5e", body: "#e3e2c8", ink: "#3f4022" },
  Ferncove: { cap: "#5f7f63", body: "#d3dfd0", ink: "#26392a" },
};
const SPARE = [
  { cap: "#a5806a", body: "#eadccf", ink: "#4a3527" },
  { cap: "#8e8a9e", body: "#e2e0e8", ink: "#37344a" },
  { cap: "#9a7d5a", body: "#ece0cc", ink: "#45351f" },
];
function colours(brand: string) {
  if (BRAND[brand]) return BRAND[brand];
  let h = 0;
  for (const c of brand) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return SPARE[h % SPARE.length];
}

const LABEL = "#fbf9f5";
const EDGE = "rgba(28,26,23,0.22)";

/** Split a name into 1-3 balanced lines and pick the largest font that fits the label box. */
function fit(name: string, w: number, h: number, brandFs: number) {
  const words = name.split(/\s+/).filter(Boolean);
  let best = { lines: [name], fs: 0 };
  for (let n = 1; n <= Math.min(3, words.length); n++) {
    const target = Math.ceil(name.length / n);
    const lines: string[] = [];
    let cur = "";
    for (const wd of words) {
      if (cur && (cur + " " + wd).length > target && lines.length < n - 1) {
        lines.push(cur);
        cur = wd;
      } else cur = cur ? `${cur} ${wd}` : wd;
    }
    lines.push(cur);
    const longest = Math.max(...lines.map((l) => l.length));
    const byW = w / (longest * 0.56);
    const byH = (h - brandFs * 1.9) / (lines.length * 1.18);
    const fs = Math.min(13, byW, byH);
    if (fs > best.fs) best = { lines, fs };
  }
  return best;
}

function Label({ art, x, y, w, h, ink }: { art: Art; x: number; y: number; w: number; h: number; ink: string }) {
  const brandFs = Math.max(4.2, Math.min(6.5, w / (art.brand.length * 0.72)));
  const { lines, fs } = fit(art.name, w - 6, h - 6, brandFs);
  const cx = x + w / 2;
  const block = brandFs * 1.9 + lines.length * fs * 1.18;
  const top = y + (h - block) / 2 + brandFs;
  return (
    <g fontFamily="Inter Variable, Inter, system-ui, sans-serif" textAnchor="middle">
      <rect x={x} y={y} width={w} height={h} rx="3" fill={LABEL} />
      <text x={cx} y={top.toFixed(2)} fontSize={brandFs.toFixed(2)} letterSpacing="0.6" fill={ink} opacity="0.8">
        {art.brand.toUpperCase()}
      </text>
      <text fontSize={fs.toFixed(2)} fill={ink} fontWeight="600">
        {lines.map((l, i) => (
          <tspan key={i} x={cx} y={(top + brandFs * 0.9 + (i + 1) * fs * 1.18).toFixed(2)}>
            {l}
          </tspan>
        ))}
      </text>
    </g>
  );
}

export function ProductArt({ product, size = 64 }: { product: Art; size?: number }) {
  const shape = shapeOf(product);
  const c = colours(product.brand);
  const s = { stroke: EDGE, strokeWidth: 1.2 };
  return (
    <svg
      className="productart"
      width={size}
      height={(size * 4) / 3}
      viewBox="0 0 120 160"
      role="img"
      aria-label={`${product.name} by ${product.brand} (illustration)`}
    >
      {shape === "pump" && (
        <g>
          <rect x="58" y="12" width="34" height="8" rx="3" fill={c.cap} {...s} />
          <rect x="55" y="18" width="10" height="16" fill={c.cap} {...s} />
          <rect x="44" y="32" width="32" height="13" rx="3" fill={c.cap} {...s} />
          <rect x="30" y="44" width="60" height="108" rx="12" fill={c.body} {...s} />
          <Label art={product} x={36} y={66} w={48} h={66} ink={c.ink} />
        </g>
      )}
      {shape === "dropper" && (
        <g>
          <rect x="51" y="4" width="18" height="24" rx="9" fill={c.cap} {...s} />
          <rect x="44" y="26" width="32" height="16" rx="3" fill={c.cap} {...s} />
          <path d="M36 50a8 8 0 0 1 8-8h32a8 8 0 0 1 8 8v88a12 12 0 0 1-12 12H48a12 12 0 0 1-12-12z" fill={c.body} {...s} />
          <Label art={product} x={41} y={68} w={38} h={62} ink={c.ink} />
        </g>
      )}
      {shape === "jar" && (
        <g>
          <rect x="14" y="54" width="92" height="26" rx="5" fill={c.cap} {...s} />
          <path d="M18 80h84v54a14 14 0 0 1-14 14H32a14 14 0 0 1-14-14z" fill={c.body} {...s} />
          <Label art={product} x={26} y={88} w={68} h={48} ink={c.ink} />
        </g>
      )}
      {shape === "tube" && (
        <g>
          <rect x="28" y="6" width="64" height="10" rx="2" fill={c.body} {...s} />
          <path d="M28 16h64l-10 110H38z" fill={c.body} {...s} />
          <rect x="38" y="124" width="44" height="30" rx="5" fill={c.cap} {...s} />
          <Label art={product} x={38} y={30} w={44} h={70} ink={c.ink} />
        </g>
      )}
      {shape === "slimtube" && (
        <g>
          <rect x="38" y="6" width="44" height="9" rx="2" fill={c.body} {...s} />
          <path d="M38 15h44l-6 102H44z" fill={c.body} {...s} />
          <rect x="44" y="115" width="32" height="40" rx="7" fill={c.cap} {...s} />
          <Label art={product} x={43} y={28} w={34} h={72} ink={c.ink} />
        </g>
      )}
      {shape === "mist" && (
        <g>
          <rect x="53" y="6" width="14" height="10" rx="2" fill={c.cap} {...s} />
          <rect x="46" y="16" width="28" height="22" rx="5" fill={c.cap} {...s} />
          <path d="M40 38h40v104a10 10 0 0 1-10 10H50a10 10 0 0 1-10-10z" fill={c.body} {...s} />
          <Label art={product} x={44} y={62} w={32} h={66} ink={c.ink} />
        </g>
      )}
    </svg>
  );
}

/** Pack art for a row that only carries ids and names (skipped items): look the product up. */
export function artFor(catalog: Record<string, Product>, id: string, fallback: { brand: string; name: string; job?: string }): Art {
  const p = catalog[id];
  if (p) return p;
  const role: Product["role"] = fallback.job === "cleanser" ? "cleanser" : fallback.job === "sunscreen" ? "sunscreen" : "moisturiser";
  return { role, brand: fallback.brand, name: fallback.name };
}
