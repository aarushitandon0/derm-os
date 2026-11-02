import { ProductArt } from "./ProductArt";
import { ZONE_COLOUR } from "../basketCopy";

// The home illustration: the face-outline motif with its two zones tinted, and three packs from
// the fictional shop in front of it. Decorative only (the words around it say the same thing).
const PACKS = [
  { role: "cleanser" as const, brand: "Saltmint", name: "Clear Gel Cleanser" },
  { role: "moisturiser" as const, brand: "Duneglow", name: "Dewy Water Cream" },
  { role: "sunscreen" as const, brand: "Kora Labs", name: "Second Skin Glow Tint SPF 40" },
];

export function HomeArt() {
  return (
    <div className="homeart" aria-hidden>
      <svg className="homeart__face" viewBox="0 0 320 340">
        <circle cx="200" cy="150" r="140" fill="var(--card)" />
        <circle cx="96" cy="270" r="70" fill="var(--card-2)" />
        <ellipse cx="160" cy="160" rx="104" ry="134" fill="#e4cdb8" />
        <line x1="160" y1="14" x2="160" y2="306" stroke="var(--raised)" strokeWidth="1.5" />
        <line x1="34" y1="160" x2="286" y2="160" stroke="var(--raised)" strokeWidth="1.5" />
        <path
          d="M98 76 Q160 44 222 76 L222 112 Q190 120 174 122 L174 222 L146 222 L146 122 Q130 120 98 112 Z"
          fill={ZONE_COLOUR.oily}
          opacity="0.7"
        />
        <ellipse cx="160" cy="262" rx="26" ry="14" fill={ZONE_COLOUR.oily} opacity="0.7" />
        <ellipse cx="100" cy="196" rx="30" ry="38" fill={ZONE_COLOUR.normal} opacity="0.7" />
        <ellipse cx="220" cy="196" rx="30" ry="38" fill={ZONE_COLOUR.normal} opacity="0.7" />
        <ellipse cx="160" cy="160" rx="104" ry="134" fill="none" stroke="var(--ink-2)" strokeWidth="1.8" />
        <path d="M118 146 q13 -8 26 0" stroke="var(--ink)" strokeWidth="2.4" fill="none" strokeLinecap="round" />
        <path d="M176 146 q13 -8 26 0" stroke="var(--ink)" strokeWidth="2.4" fill="none" strokeLinecap="round" />
        <path d="M140 244 q20 11 40 0" stroke="var(--ink)" strokeWidth="2.4" fill="none" strokeLinecap="round" />
        <g fontFamily="var(--sans)" fontSize="12" fontWeight="600" fill="var(--ink)" textAnchor="middle">
          <text x="160" y="94">T-zone</text>
          <text x="100" y="200">Cheek</text>
          <text x="220" y="200">Cheek</text>
        </g>
      </svg>
      <div className="homeart__packs">
        {PACKS.map((p) => (
          <span key={p.name} className="homeart__pack">
            <ProductArt product={p} size={88} />
          </span>
        ))}
      </div>
    </div>
  );
}
