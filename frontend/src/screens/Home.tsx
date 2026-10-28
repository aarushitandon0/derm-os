import { useState } from "react";
import { api } from "../api";
import { addDays, concernLabel, daysSince, fmtLong, NOT_DIAGNOSIS } from "../copy";
import { ProductArt } from "../components/ProductArt";
import { plusTarget } from "../components/TabBar";
import { Btn, NavBar, PageHead, RowLink, Section, Wordmark } from "../components/ui";
import { href } from "../router";
import { useStore } from "../store";

export default function Home() {
  const { activeTrial: t, catalog, health, shelf, history, refresh, activeBaselineCount } = useStore();
  const [resetting, setResetting] = useState(false);
  const product = t ? catalog[t.product_id] : undefined;

  const nextCheck = t
    ? t.checkpoints_days.map((d) => ({ d, at: addDays(t.started_at, d) })).find((c) => c.at.getTime() > Date.now()) ?? null
    : null;
  const next = plusTarget(t?.id, activeBaselineCount);

  const reset = async () => {
    if (!confirm("Clear the shelf, history, trials and scans for a fresh demo take?")) return;
    setResetting(true);
    await api.demoReset().catch(() => null);
    await refresh();
    setResetting(false);
  };

  return (
    <div className="page">
      <NavBar left={<Wordmark />} />
      <PageHead title="Your skin, with context." lede="Same face, same light, one change, honest verdict." />

      {t && product && (
        <a className="trialcard" href={href(`/trial/${t.id}`)}>
          <span className="trialcard__art">
            <ProductArt product={product} size={46} />
          </span>
          <span className="trialcard__body">
            <span className="trialcard__kicker">Current experiment · day {daysSince(t.started_at)}</span>
            <span className="trialcard__name">{product.name}</span>
            <span className="trialcard__sub">
              Watching {concernLabel(t.goal_concern).toLowerCase()} ·{" "}
              {activeBaselineCount < 3
                ? `baseline ${activeBaselineCount} of 3`
                : nextCheck
                ? `next check-in ${fmtLong(nextCheck.at)}`
                : "check-ins due"}
            </span>
          </span>
        </a>
      )}
      {t && (
        <div className="actions">
          <Btn to={next.to} wide>
            {next.label}
          </Btn>
        </div>
      )}

      <Section label="What would you like to do?">
        <div className="rows">
          <RowLink
            to={shelf.length ? "/history" : "/shelf"}
            icon="search"
            title="Start"
            sub={
              shelf.length
                ? `${shelf.length} products on your shelf, ${history.length} history record${history.length === 1 ? "" : "s"}`
                : "Where do I begin? Add your routine and history"
            }
          />
          <RowLink to="/compare" icon="compare" title="Compare" sub="Should I buy this? Checked against your history" />
          <RowLink
            to={t ? `/results/${t.id}` : "/progress"}
            icon="progress"
            title="Review"
            sub={t ? "Is it working? See what your scans can and can't say" : "Start a trial first, so there's a baseline"}
          />
          <RowLink to={t ? `/brief/${t.id}` : "/brief"} icon="file" title="Visit brief" sub="One page for a dermatologist" />
        </div>
      </Section>

      {health?.demo_mode && (
        <div className="demobox">
          <p>
            <strong>Demo mode is on.</strong> Scans replay prepared YouCam results; no units are spent.
          </p>
          {health.server_demo_mode !== false && (
            <Btn kind="quiet" onClick={reset} disabled={resetting}>
              {resetting ? "Clearing…" : "Reset demo data"}
            </Btn>
          )}
        </div>
      )}

      <p className="foot small">
        {NOT_DIAGNOSIS} Skin measurements by YouCam AI Skin Analysis. All products shown are fictional.{" "}
        <a href={href("/welcome")}>Welcome screen</a>
      </p>
    </div>
  );
}
