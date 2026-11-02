import type { FaceMapData } from "../api";
import { ZONE_COLOUR, ZONE_KEY, ZONE_WORD } from "../basketCopy";

/**
 * A stylised face with the two zones coloured by type and labelled on the drawing, a colour key in
 * words, and one plain line per zone beside it. Words only: the face map never shows a number
 * about the skin.
 */
export function FaceMap({ map }: { map: FaceMapData }) {
  const t = map.zones.find((z) => z.zone === "t_zone");
  const u = map.zones.find((z) => z.zone === "u_zone");
  const tc = ZONE_COLOUR[t?.type ?? "normal"];
  const uc = ZONE_COLOUR[u?.type ?? "normal"];
  const skin = map.undertone.skin_color ?? "#d6b49a";
  const label = map.zones.map((z) => z.line).join(", ");
  const tag = { fontSize: 11, fontWeight: 600, fill: "var(--ink)", textAnchor: "middle" as const, fontFamily: "var(--sans)" };

  return (
    <figure className="facemap">
      <svg viewBox="0 0 200 250" className="facemap__svg" role="img" aria-label={`Face map: ${label}`}>
        <ellipse cx="100" cy="126" rx="76" ry="98" fill={skin} opacity="0.5" />
        {/* the face-outline motif: outline plus faint centre lines */}
        <line x1="100" y1="22" x2="100" y2="230" stroke="var(--raised)" strokeWidth="1.2" opacity="0.9" />
        <line x1="18" y1="126" x2="182" y2="126" stroke="var(--raised)" strokeWidth="1.2" opacity="0.9" />
        <ellipse cx="100" cy="126" rx="76" ry="98" fill="none" stroke="var(--ink-2)" strokeWidth="1.5" />
        {/* Cheeks (U-zone) */}
        <ellipse cx="54" cy="156" rx="24" ry="30" fill={uc} opacity="0.75" />
        <ellipse cx="146" cy="156" rx="24" ry="30" fill={uc} opacity="0.75" />
        {/* T-zone: forehead band, nose, chin */}
        <path d="M50 60 Q100 36 150 60 L150 88 Q124 94 112 96 L112 172 L88 172 L88 96 Q76 94 50 88 Z" fill={tc} opacity="0.78" />
        <ellipse cx="100" cy="204" rx="20" ry="11" fill={tc} opacity="0.78" />
        {/* features */}
        <path d="M68 114 q10 -6 20 0" stroke="var(--ink)" strokeWidth="2" fill="none" strokeLinecap="round" />
        <path d="M112 114 q10 -6 20 0" stroke="var(--ink)" strokeWidth="2" fill="none" strokeLinecap="round" />
        <path d="M84 188 q16 9 32 0" stroke="var(--ink)" strokeWidth="2" fill="none" strokeLinecap="round" />
        {/* zone names on the drawing */}
        <text x="100" y="74" {...tag}>T-zone</text>
        <text x="54" y="160" {...tag}>Cheek</text>
        <text x="146" y="160" {...tag}>Cheek</text>
      </svg>
      <figcaption className="facemap__legend">
        {map.zones.map((z) => (
          <p key={z.zone} className="facemap__zone">
            <span className="facemap__dot" style={{ background: ZONE_COLOUR[z.type] }} aria-hidden />
            <span>
              <strong>{z.line}</strong>
              <span className="facemap__hint">{ZONE_WORD[z.type]}</span>
              <span className="facemap__src">{z.label}</span>
            </span>
          </p>
        ))}
        <p className="facemap__zone">
          <span className="facemap__dot facemap__dot--tone" style={{ background: skin }} aria-hidden />
          <span>
            <strong>{map.undertone.line}</strong>
            <span className="facemap__src">{map.undertone.label}</span>
          </span>
        </p>
        <p className="facemap__key">
          <span className="sr-only">Colour key: </span>
          {ZONE_KEY.map((k) => (
            <span key={k.type} className="facemap__keyitem">
              <span className="facemap__dot facemap__dot--sm" style={{ background: ZONE_COLOUR[k.type] }} aria-hidden />
              {k.word}
            </span>
          ))}
        </p>
      </figcaption>
    </figure>
  );
}
