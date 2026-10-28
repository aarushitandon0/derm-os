import { useEffect, useState } from "react";
import { api, type Evidence } from "../api";
import { concernLabel, NOISE_CAPTION } from "../copy";
import { Icon } from "../components/Icon";
import { ProgressChart } from "../components/ProgressChart";
import { Btn, Loading, NavBar, Notice, PageHead, PreparedTag, Segmented, TabPanel } from "../components/ui";
import { useStore } from "../store";

export default function Progress({ trialId }: { trialId?: string | null }) {
  const { activeTrial, trials, meta, catalog } = useStore();
  const trial = (trialId && trials.find((t) => t.id === trialId)) || activeTrial || trials[trials.length - 1] || null;
  const [ev, setEv] = useState<Evidence | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [concern, setConcern] = useState<string | null>(null);

  useEffect(() => {
    if (!trial) return;
    setEv(null);
    api.evidence(trial.id).then(setEv, (e) => setErr((e as Error).message));
  }, [trial?.id]);

  if (!trial)
    return (
      <div className="page">
        <NavBar />
        <PageHead title="Progress" lede="Nothing to chart yet." />
        <div className="empty">
          <Icon name="progress" size={28} />
          <p>Progress starts with a trial: one change, a 3-photo baseline, then check-ins compared with it.</p>
          <Btn to="/compare" wide>
            Plan a trial
          </Btn>
        </div>
      </div>
    );

  const product = catalog[trial.product_id];
  const head = (
    <PageHead title="Progress" lede={`${product?.name ?? "Trial"} · watching ${concernLabel(trial.goal_concern).toLowerCase()}`} />
  );

  if (err)
    return (
      <div className="page">
        <NavBar />
        {head}
        <Notice tone="stop">{err}</Notice>
      </div>
    );
  if (!ev)
    return (
      <div className="page">
        <NavBar />
        {head}
        <Loading label="Reading your scans" />
      </div>
    );

  const scanned = new Set<string>(Object.keys(ev.baseline_ranges));
  ev.series.forEach((c) => Object.keys(c.raw_scores ?? {}).forEach((k) => scanned.add(k)));
  const goal = trial.goal_concern;
  const concerns = [goal, ...[...scanned].filter((k) => k !== goal).sort()];
  const active = concern && concerns.includes(concern) ? concern : goal;
  const prepared = ev.series.some((c) => c.source === "replay");
  const hasData = ev.series.some((c) => typeof c.raw_scores?.[active] === "number");

  return (
    <div className="page">
      <NavBar />
      {head}
      {prepared && (
        <p className="tagline">
          <PreparedTag /> Scores are prepared data; light and framing come from the real photos.
        </p>
      )}
      <div className="hscroll">
        <Segmented
          idBase="progress"
          label="Concern"
          value={active}
          onChange={setConcern}
          options={concerns.map((c) => ({ value: c, label: concernLabel(c) }))}
        />
      </div>
      <TabPanel idBase="progress" value={active}>
        {hasData ? (
          <ProgressChart ev={ev} concern={active} band={meta?.min_band ?? 0} productName={product?.name ?? "trial"} />
        ) : (
          <div className="empty">
            <p>No scans yet for {concernLabel(active).toLowerCase()}. Take your baseline to start the chart.</p>
            <Btn to={`/capture?mode=baseline&trial=${trial.id}`} wide>
              Take baseline
            </Btn>
          </div>
        )}
        {active !== goal && hasData && (
          <p className="small muted">For reference: this trial judges {concernLabel(goal).toLowerCase()}, not {concernLabel(active).toLowerCase()}.</p>
        )}
      </TabPanel>
      <div className="callout">
        <Icon name="wave" size={22} />
        <p>{NOISE_CAPTION}</p>
      </div>
      <div className="actions">
        <Btn kind="ghost" to={`/results/${trial.id}`} wide>
          See latest results
        </Btn>
      </div>
    </div>
  );
}
