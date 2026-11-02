import type { FaceMapData, ScanFindings } from "../api";
import { BASKET, ZONE_COLOUR, ZONE_KEY, ZONE_WORD } from "../basketCopy";

/**
 * "What your scan found": one plain line per concern YouCam measured, banded on the server
 * (app/findings.py). Words only. A concern that wasn't measured has no line. `linkTo` (an element id)
 * scrolls each line's need to the basket cards; without it (a saved scan) the need is named, not linked.
 */
export function ScanFindingsBlock({ findings, linkTo, demo }: { findings?: ScanFindings | null; linkTo?: string; demo?: boolean }) {
  if (!findings || findings.lines.length === 0) return null;
  return (
    <div className="findings">
      <p className="findings__title">{BASKET.findingsLabel}</p>
      <ul className="findings__list">
        {findings.lines.map((l) => (
          <li key={l.concern} className={`findings__line findings__line--${l.band}`}>
            <span>{l.line}</span>
            {l.need &&
              (linkTo ? (
                <button
                  type="button"
                  className="findings__need findings__need--link"
                  onClick={() => document.getElementById(linkTo)?.scrollIntoView({ behavior: "smooth", block: "start" })}
                >
                  → {BASKET.findingsWhy} {l.need.line}
                </button>
              ) : (
                <span className="findings__need">
                  → {BASKET.findingsDrives} {l.need.line}
                </span>
              ))}
            {l.see_doctor && <span className="findings__doc">{l.see_doctor}</span>}
          </li>
        ))}
      </ul>
      <p className="facemap__src">
        {findings.label}
        {demo ? " · demo data" : ""}
      </p>
    </div>
  );
}

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
