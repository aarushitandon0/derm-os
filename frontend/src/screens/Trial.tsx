import { useCallback, useEffect, useState } from "react";
import { api, type Evidence } from "../api";
import { addDays, CHECK, concernLabel, daysSince, fmtDate, fmtLong, symptomLabel } from "../copy";
import { buildIcs, downloadIcs, upcomingCheckins } from "../ics";
import { Icon } from "../components/Icon";
import { ProductArt } from "../components/ProductArt";
import { StopCard } from "../components/Reactions";
import { TrialNotes } from "../components/TrialNotes";
import { Btn, Loading, NavBar, Notice, RowLink, Section } from "../components/ui";
import { useStore } from "../store";

export default function Trial({ id }: { id: string }) {
  const { catalog, meta, refresh } = useStore();
  const [ev, setEv] = useState<Evidence | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    api.evidence(id).then(setEv, (e) => setErr((e as Error).message));
  }, [id]);
  useEffect(load, [load]);

  if (err)
    return (
      <div className="page">
        <NavBar back="/routine" />
        <Notice tone="stop">{err}</Notice>
      </div>
    );
  if (!ev)
    return (
      <div className="page">
        <NavBar back="/routine" />
        <Loading />
      </div>
    );

  const t = ev.trial;
  const p = ev.product;
  const nBase = ev.captures.baseline.length;
  const day = daysSince(t.started_at);
  const lastDay = Math.max(...t.checkpoints_days, 0);
  const upcoming = upcomingCheckins(t.started_at, t.checkpoints_days);
  const concern = concernLabel(t.goal_concern).toLowerCase();

  const remind = () =>
    downloadIcs(`dermos-check-ins-${p.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.ics`, buildIcs(t.id, p.name, concern, upcoming));

  return (
    <div className="page page--hero">
      <div className="producthero">
        <NavBar back="/routine" />
        <ProductArt product={p} size={92} />
      </div>
      <div className="pagehead">
        <h1 className="title">{p.name}</h1>
        <p className="subtitle">
          {p.brand} · started {fmtLong(t.started_at)}
        </p>
      </div>

      <StopCard
        trialId={t.id}
        productName={p.name}
        reactions={ev.reactions}
        onChanged={() => {
          load();
          void refresh();
        }}
      />

      <div className="rows">
        <RowLink
          icon="clock"
          title={day <= lastDay ? `Day ${day} of ${lastDay}` : `Day ${day} · all check-ins due`}
          sub={`${p.leave_on ? "Leave-on" : "Wash-off"} · exclusion check: ${CHECK[t.check.status].label.toLowerCase()}`}
        />
      </div>

      <Section label="Why this experiment?">
        <p className="prose">
          Testing {p.name} for {concern}, one change with the rest of your routine held steady. Check-ins on{" "}
          {t.checkpoints_days.map((d) => `day ${d}`).join(" and ")} are compared with your baseline range, using your personal
          noise floor.
        </p>
        {t.check.status === "unknown" && <p className="small muted">{t.check.reasons[0]}</p>}
      </Section>

      <div className="actions">
        {nBase < 3 ? (
          <Btn to={`/capture?mode=baseline&trial=${t.id}`} wide>
            {nBase ? `Finish baseline (${nBase} of 3)` : "Take baseline photos"}
          </Btn>
        ) : (
          <Btn to={`/checkin/${t.id}`} wide>
            Check in
          </Btn>
        )}
      </div>

      <div className="rows">
        {upcoming.length > 0 && (
          <RowLink
            icon="bell"
            title="Set a reminder"
            sub={`Adds ${upcoming.map((c) => `day ${c.day}`).join(" and ")} to your calendar (.ics)`}
            onClick={remind}
            trailing={<Icon name="chevron" size={18} />}
          />
        )}
        <RowLink to={`/results/${t.id}`} icon="progress" title="Results so far" sub="What the scans can and can't say" />
        <RowLink to={`/brief/${t.id}`} icon="file" title="Visit brief" sub="One page for an appointment" />
      </div>

      <Section label="Notes">
        <TrialNotes trialId={t.id} />
      </Section>

      <Section label="The plan">
        <dl className="facts">
          <div>
            <dt>Holding fixed</dt>
            <dd>
              {t.held_fixed.length ? (
                <ul className="plainlist">
                  {t.held_fixed.map((h) => (
                    <li key={h}>{catalog[h]?.name ?? h}</li>
                  ))}
                </ul>
              ) : (
                "Everything else in your routine."
              )}
              <span className="small muted">
                Starting another leave-on product during this trial means the result can't say which one did what.
              </span>
            </dd>
          </div>
          <div>
            <dt>Check-ins</dt>
            <dd>
              <ul className="plainlist">
                <li>
                  Day 0: baseline, 3 photos{nBase ? ` (${Math.min(nBase, 3)} of 3 done)` : ""}
                </li>
                {t.checkpoints_days.map((d) => (
                  <li key={d}>
                    Day {d}: {fmtDate(addDays(t.started_at, d))}, 2 photos
                  </li>
                ))}
              </ul>
            </dd>
          </div>
          <div>
            <dt>Stop if</dt>
            <dd>
              <p className="stoplist">{(meta?.stop_symptoms ?? []).map(symptomLabel).join(" · ")}</p>
              <span className="small muted">Any of these outranks a better-looking score. Pause the product and log it.</span>
            </dd>
          </div>
        </dl>
      </Section>
    </div>
  );
}
