import type { FaceMapData } from "../api";
import { ZONE_COLOUR, ZONE_WORD } from "../basketCopy";

/**
 * A stylised face with the two zones coloured by type, and one plain line per zone beside it.
 * Words only: the face map never shows a number about the skin.
 */
export function FaceMap({ map }: { map: FaceMapData }) {
  const t = map.zones.find((z) => z.zone === "t_zone");
  const u = map.zones.find((z) => z.zone === "u_zone");
  const tc = ZONE_COLOUR[t?.type ?? "normal"];
  const uc = ZONE_COLOUR[u?.type ?? "normal"];
  const skin = map.undertone.skin_color ?? "#d6b49a";
  const label = map.zones.map((z) => z.line).join(", ");

  return (
    <figure className="facemap">
      <svg viewBox="0 0 200 240" className="facemap__svg" role="img" aria-label={`Face map: ${label}`}>
        <ellipse cx="100" cy="122" rx="74" ry="96" fill={skin} opacity="0.55" />
        <ellipse cx="100" cy="122" rx="74" ry="96" fill="none" stroke="var(--ink-2)" strokeWidth="1.5" />
        {/* Cheeks (U-zone) */}
        <ellipse cx="56" cy="150" rx="24" ry="30" fill={uc} opacity="0.7" />
        <ellipse cx="144" cy="150" rx="24" ry="30" fill={uc} opacity="0.7" />
        {/* T-zone: forehead band, nose, chin */}
        <path
          d="M52 58 Q100 34 148 58 L148 84 Q124 90 112 92 L112 168 L88 168 L88 92 Q76 90 52 84 Z"
          fill={tc}
          opacity="0.72"
        />
        <ellipse cx="100" cy="198" rx="20" ry="11" fill={tc} opacity="0.72" />
        {/* features */}
        <path d="M70 108 q10 -6 20 0" stroke="var(--ink)" strokeWidth="2" fill="none" strokeLinecap="round" />
        <path d="M110 108 q10 -6 20 0" stroke="var(--ink)" strokeWidth="2" fill="none" strokeLinecap="round" />
        <path d="M84 182 q16 9 32 0" stroke="var(--ink)" strokeWidth="2" fill="none" strokeLinecap="round" />
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
      </figcaption>
    </figure>
  );
}
