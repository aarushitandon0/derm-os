import { useState } from "react";
import { api } from "../api";
import {
  addDays,
  concernLabel,
  daysSince,
  fmtLong,
  HOME_QUESTION,
  HOME_VALUE_LINE,
  MOMENTS,
  NOT_DIAGNOSIS,
  START_HERE,
} from "../copy";
import { BASKET } from "../basketCopy";
import { ProductArt } from "../components/ProductArt";
import { plusTarget } from "../components/TabBar";
import { Btn, NavBar, PageHead, RowLink, Section, Wordmark } from "../components/ui";
import { href } from "../router";
import { useStore } from "../store";

// Home is the moment, not a dashboard (docs/STRATEGY.md section 4). It asks one question and
// offers the three moments people actually have, plus a way in for someone with no history yet.
export default function Home() {
  const { activeTrial: t, catalog, health, shelf, history, outcomes, refresh, activeBaselineCount } = useStore();
  const [resetting, setResetting] = useState(false);
  const product = t ? catalog[t.product_id] : undefined;

  const nextCheck = t
    ? t.checkpoints_days.map((d) => ({ d, at: addDays(t.started_at, d) })).find((c) => c.at.getTime() > Date.now()) ?? null
    : null;
  const next = plusTarget(t?.id, activeBaselineCount);

  const reset = async () => {
    if (!confirm("Clear the shelf, history, outcomes, trials and scans for a fresh demo take?")) return;
    setResetting(true);
    await api.demoReset().catch(() => null);
    await refresh();
    setResetting(false);
  };

  return (
    <div className="page">
      <NavBar left={<Wordmark />} />
      <PageHead eyebrow={BASKET.usp} title={HOME_QUESTION} lede={HOME_VALUE_LINE} />

      {/* Strategy v2: the basket is the headline; breakout and check-in are the smaller options. */}
      <a className="hero" href={href("/basket")}>
        <span className="hero__label">{BASKET.hero}</span>
        <span className="hero__sub">{BASKET.heroSub}</span>
      </a>

      <div className="moments moments--small" role="group" aria-label={HOME_QUESTION}>
        {MOMENTS.filter((m) => m.id !== "buy").map((m) => (
          <a key={m.id} className={`moment moment--small moment--${m.id}`} href={href(m.to)}>
            <span className="moment__label">{m.label}</span>
            <span className="moment__sub">{m.sub}</span>
          </a>
        ))}
      </div>
      <p className="small">
        <a href={href("/store")}>Check one product from the sale</a>
      </p>

      <a className="starthere" href={href(START_HERE.to)}>
        <span className="starthere__label">{START_HERE.label}</span>
        <span className="starthere__sub">{START_HERE.sub}</span>
      </a>

      {t && product && (
        <Section label="Your current trial">
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
          <div className="actions">
            <Btn to={next.to} wide>
              {next.label}
            </Btn>
          </div>
        </Section>
      )}

      <Section label="Your record">
        <div className="rows">
          <RowLink
            to="/history"
            icon="search"
            title="What happened, product by product"
            sub={
              outcomes.length || history.length
                ? `${outcomes.length} outcome${outcomes.length === 1 ? "" : "s"}, ${history.length} record${
                    history.length === 1 ? "" : "s"
                  }`
                : "Nothing recorded yet. Add what suited you and what didn't."
            }
          />
          <RowLink
            to="/shelf"
            icon="routine"
            title="Your shelf"
            sub={shelf.length ? `${shelf.length} products you're using` : "Add what you're using now"}
          />
          <RowLink to={t ? `/brief/${t.id}` : "/brief"} icon="file" title="Visit brief" sub="One page for a dermatologist" />
        </div>
      </Section>

      {health?.demo_mode && (
        <div className="demobox">
          <p>
            <strong>Demo mode is on.</strong> Scans replay prepared YouCam results; no units are spent.
          </p>
          <div className="demobox__btns">
            <Btn kind="quiet" to="/demo">
              Guided demo
            </Btn>
            {health.server_demo_mode !== false && (
              <Btn kind="quiet" onClick={reset} disabled={resetting}>
                {resetting ? "Clearing…" : "Reset demo data"}
              </Btn>
            )}
          </div>
        </div>
      )}

      <p className="foot small">
        {NOT_DIAGNOSIS} Skin measurements by YouCam AI Skin Analysis. All products shown are fictional.{" "}
        <a href={href("/welcome")}>Welcome screen</a>
      </p>
    </div>
  );
}
