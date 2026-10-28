import { useEffect, useState } from "react";
import { api, assetUrl, type Evidence } from "../api";
import { CHECK, concernLabel, fmtDate, fmtLong, MASKS_DEMO, RECORD, symptomLabel } from "../copy";
import { Icon } from "../components/Icon";
import { useTrialNotes } from "../components/TrialNotes";
import { Btn, Loading, NavBar, Notice, PageHead, PreparedTag, Segmented, TabPanel, Wordmark } from "../components/ui";
import { useStore } from "../store";

// One printable page the user edits before taking it to an appointment.
export default function Brief({ id }: { id?: string }) {
  const { activeTrial, trials } = useStore();
  const trialId = id || activeTrial?.id || trials[trials.length - 1]?.id;
  if (!trialId)
    return (
      <div className="page">
        <NavBar back="/" />
        <PageHead title="Visit brief" lede="A clear summary to share with your dermatologist." />
        <div className="empty">
          <Icon name="file" size={28} />
          <p>A brief is built from a trial: what you tried, what you felt and what the scans could and couldn't say. Your history records go in too.</p>
          <Btn to="/history" wide>
            Record your history
          </Btn>
          <Btn kind="ghost" to="/compare" wide>
            Plan a trial
          </Btn>
        </div>
      </div>
    );
  return <BriefFor id={trialId} key={trialId} />;
}

function BriefFor({ id }: { id: string }) {
  const { catalog, history } = useStore();
  const [ev, setEv] = useState<Evidence | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<"summary" | "photos">("summary");
  const [notes, setNotes] = useTrialNotes(id);

  useEffect(() => {
    api.evidence(id).then(setEv, (e) => setErr((e as Error).message));
  }, [id]);

  const printIt = () => window.print();
  const nav = (
    <NavBar
      back={`/trial/${id}`}
      right={
        <button type="button" className="iconbtn" onClick={printIt} aria-label="Export PDF">
          <Icon name="share" />
        </button>
      }
    />
  );

  if (err)
    return (
      <div className="page">
        {nav}
        <Notice tone="stop">{err}</Notice>
      </div>
    );
  if (!ev)
    return (
      <div className="page">
        {nav}
        <Loading />
      </div>
    );

  const { trial: t, report: r, product: p } = ev;
  const prepared = ev.series.some((c) => c.source === "replay");
  const others = [...new Set(t.checkins.flatMap((c) => c.other_new_leave_on))].map((o) => catalog[o]?.name ?? o);
  const mild = t.checkins.filter((c) => c.symptoms.some((s) => !ev.reactions.some((x) => x.symptom === s.toLowerCase().trim())));

  const points: string[] = [
    `Watching: ${concernLabel(t.goal_concern).toLowerCase()}.`,
    `Currently testing: ${p.name} (${p.brand}, ${p.leave_on ? "leave-on" : "wash-off"}), since ${fmtLong(t.started_at)}.`,
    `So far: ${r.message}`,
    ...ev.reactions.map(
      (x) =>
        `Reported ${symptomLabel(x.symptom).toLowerCase()} on ${fmtLong(x.logged_at)}; ${
          x.resolved && x.resolved_on ? `marked resolved as of ${fmtLong(x.resolved_on + "T12:00:00")}` : "not resolved yet"
        }.`
    ),
    others.length ? `Also started during the trial: ${others.join(", ")}.` : "No other new leave-on products logged.",
  ];

  return (
    <div className="page page--brief">
      {nav}
      <div className="no-print">
        <PageHead title="Visit brief" lede="A clear summary to share with your dermatologist." />
        <Segmented
          idBase="brief"
          label="Brief sections"
          value={tab}
          onChange={setTab}
          options={[
            { value: "summary", label: "Summary" },
            { value: "photos", label: "Photos" },
          ]}
        />
      </div>

      <div className={tab === "summary" ? "" : "screen-hidden"}>
        <TabPanel idBase="brief" value="summary">
          <article className="brief">
            <header className="brief__head print-only">
              <Wordmark />
              <h1 className="brief__title">Visit brief</h1>
            </header>
            <p className="small muted">
              Prepared by the patient on {fmtLong(new Date())}. Self-recorded; not clinically reviewed; not a diagnosis.{" "}
              {prepared && <PreparedTag />}
            </p>

            <section className="brief__sec">
              <h2 className="h3">Key points</h2>
              <ul className="bullets">
                {points.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            </section>

            <div className="exportcard no-print">
              <button type="button" className="row" onClick={printIt}>
                <span className="row__icon">
                  <Icon name="file" />
                </span>
                <span className="row__body">
                  <span className="row__title">Export PDF</span>
                  <span className="row__sub">Includes timeline, routine, key results and your notes</span>
                </span>
                <span className="row__trail">
                  <Icon name="chevron" size={18} />
                </span>
              </button>
            </div>

            <section className="brief__sec">
              <h2 className="h3">Symptoms logged</h2>
              {ev.reactions.length || mild.length ? (
                <ul className="bullets">
                  {ev.reactions.map((x) => (
                    <li key={x.id}>
                      {fmtDate(x.logged_at)}: {symptomLabel(x.symptom)} (stop sign),{" "}
                      {x.resolved ? `resolved${x.resolution_note ? `: ${x.resolution_note}` : ""}` : "unresolved"}
                    </li>
                  ))}
                  {mild.map((c) => (
                    <li key={c.at}>
                      {fmtDate(c.at)}:{" "}
                      {c.symptoms
                        .filter((s) => !ev.reactions.some((x) => x.symptom === s.toLowerCase().trim()))
                        .map(symptomLabel)
                        .join(", ")}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>None logged.</p>
              )}
            </section>

            <section className="brief__sec">
              <h2 className="h3">Timeline</h2>
              <ul className="bullets">
                {ev.timeline.map((e, i) => (
                  <li key={i}>
                    {fmtDate(e.at)}: {e.text}
                  </li>
                ))}
              </ul>
            </section>

            <section className="brief__sec">
              <h2 className="h3">Product under trial: full label</h2>
              <p className="brief__inci">{p.inci.join(", ")}</p>
              <p className="small">
                {p.inci_complete ? "Ingredient list marked complete." : "Ingredient list incomplete: some ingredients are not known."}{" "}
                Exclusion check at start: {CHECK[t.check.status].label.toLowerCase()}.
              </p>
            </section>

            <section className="brief__sec">
              <h2 className="h3">Routine during the trial</h2>
              <ul className="bullets">
                <li>
                  {p.name} ({p.brand}): new, under trial
                </li>
                {t.held_fixed.map((s) => (
                  <li key={s}>
                    {catalog[s]?.name ?? s} ({catalog[s]?.brand}): unchanged
                  </li>
                ))}
              </ul>
            </section>

            <section className="brief__sec">
              <h2 className="h3">History records</h2>
              {history.length ? (
                <ul className="bullets">
                  {history.map((h) => (
                    <li key={h.id}>
                      <strong>{RECORD[h.type].label}:</strong>{" "}
                      {h.type === "suspected_reaction" ? catalog[h.product_id ?? ""]?.name : h.ingredient}
                      {h.note ? `: ${h.note}` : ""}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>None recorded.</p>
              )}
              <p className="small">Only records marked “clinician-confirmed” were confirmed by a clinician.</p>
            </section>

            <section className="brief__sec">
              <h2 className="h3">Scan ranges (YouCam raw score)</h2>
              <table className="brief__table">
                <thead>
                  <tr>
                    <th>Concern</th>
                    <th>Baseline</th>
                    <th>Latest check-in</th>
                    <th>Overlap</th>
                  </tr>
                </thead>
                <tbody>
                  {r.findings.map((f) => (
                    <tr key={f.concern}>
                      <td>{concernLabel(f.concern)}</td>
                      <td>{f.baseline ? `${f.baseline.lo}–${f.baseline.hi} (n=${f.baseline.n})` : "–"}</td>
                      <td>{f.followup ? `${f.followup.lo}–${f.followup.hi} (n=${f.followup.n})` : "–"}</td>
                      <td>{!f.baseline || !f.followup ? "–" : f.beyond_noise ? "No" : "Yes"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {r.comparability && !r.comparability.comparable && (
                <p className="small">Scan conditions differed: {r.comparability.reasons.join(" ")}</p>
              )}
            </section>

            <section className="brief__sec">
              <h2 className="h3">Notes for the appointment</h2>
              <textarea
                className="notes__input no-print"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Questions you want to ask, anything else that changed (sleep, season, cycle, medication)…"
                rows={4}
                aria-label="Notes for the appointment"
              />
              <div className="brief__notes-print print-only">{notes || "None."}</div>
            </section>
          </article>
        </TabPanel>
      </div>

      {tab === "photos" && (
        <div className="no-print">
        <TabPanel idBase="brief" value="photos">
          <p className="prose">
            derm//os doesn't keep your photos. What it keeps are the scores, the capture conditions and, for live scans, the areas
            YouCam marked.
          </p>
          <ul className="scanlist">
            {ev.series.map((c) => (
              <li key={c.id} className="scanlist__item">
                {c.masks?.[t.goal_concern]?.[0] ? (
                  <img src={assetUrl(c.masks[t.goal_concern][0])} alt={`${concernLabel(t.goal_concern)} areas marked by YouCam, ${fmtDate(c.taken_at)}`} loading="lazy" />
                ) : (
                  <span className="scanlist__ph" aria-hidden>
                    <Icon name="frame" />
                  </span>
                )}
                <span className="row__body">
                  <span className="row__title">
                    {c.phase === "baseline" ? "Baseline" : "Check-in"} · {fmtDate(c.taken_at)}
                  </span>
                  <span className="row__sub">
                    {c.phase === "checkin" ? (c.comparable ? "Comparable" : "Not compared") : "Sets your range"}
                    {c.source === "replay" ? " · prepared data" : ""}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          {!ev.series.length && <p className="muted">No scans yet.</p>}
          {ev.series.some((c) => c.source === "replay" && !c.masks?.[t.goal_concern]?.length) && (
            <p className="muted small">{MASKS_DEMO}</p>
          )}
        </TabPanel>
        </div>
      )}
    </div>
  );
}
