import { useState } from "react";
import { api } from "../api";
import {
  addDays,
  concernLabel,
  daysSince,
  fmtLong,
  MOMENTS,
  NOT_DIAGNOSIS,
} from "../copy";
import { BASKET, HOME } from "../basketCopy";
import { HomeArt } from "../components/HomeArt";
import { ProductArt } from "../components/ProductArt";
import { plusTarget } from "../components/TabBar";
import { Btn, NavBar, RowLink, Section, Wordmark } from "../components/ui";
import { AccountButton } from "../components/Account";
import { href } from "../router";
import { useStore } from "../store";

// Home is the moment, not a dashboard (docs/strategy.md section 4): one big button, "Build my
// basket from my face", two smaller moments, and the prepared demo faces one tap away.
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
    <div className="page page--wide home">
      <NavBar left={<Wordmark />} right={<AccountButton />} />

      {/* Strategy v2 (docs/strategy.md section 4): the basket is the headline; breakout and
          check-in are the smaller options; a prepared face is one tap away. */}
      <section className="home__hero" aria-labelledby="home-title">
        <div className="home__copy">
          <h1 id="home-title" className="home__title">
            {BASKET.usp}
          </h1>
          <p className="home__lede">{HOME.lede}</p>
        </div>

        <div className="home__actions">
          <a className="hero" href={href("/basket")}>
            <span className="hero__label">{BASKET.hero}</span>
            <span className="hero__sub">{BASKET.heroSub}</span>
          </a>

          <div className="home__try">
            <p className="home__trylabel">{HOME.tryLabel}</p>
            <div className="home__trybtns">
              <a className="trybtn" href={href("/basket?demo=riya")}>
                <span className="trybtn__label">{HOME.riya}</span>
                <span className="trybtn__sub">{HOME.riyaSub}</span>
              </a>
              <a className="trybtn" href={href("/basket?demo=beginner")}>
                <span className="trybtn__label">{HOME.beginner}</span>
                <span className="trybtn__sub">{HOME.beginnerSub}</span>
              </a>
            </div>
          </div>

          <div className="moments moments--small" role="group" aria-label={HOME.otherLabel}>
            {MOMENTS.filter((m) => m.id !== "buy").map((m) => (
              <a key={m.id} className={`moment moment--small moment--${m.id}`} href={href(m.to)}>
                <span className="moment__label">{m.label}</span>
                <span className="moment__sub">{m.sub}</span>
              </a>
            ))}
          </div>
        </div>

        <div className="home__art">
          <HomeArt />
        </div>
      </section>

      <div className="home__more">
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
          <RowLink to="/store" icon="search" title={HOME.storeLink} sub="Every item has a “Check against my skin” button" />
        </div>
      </Section>

      {health?.demo_mode && (
        <div className="demobox">
          <p>
            <strong>Demo mode is on.</strong> Scans replay prepared YouCam results; no units are spent.
          </p>
          <div className="demobox__btns">
            <Btn kind="quiet" to="/demo">
              Check-in walkthrough
            </Btn>
            {health.server_demo_mode !== false && (
              <Btn kind="quiet" onClick={reset} disabled={resetting}>
                {resetting ? "Clearing…" : "Reset demo data"}
              </Btn>
            )}
          </div>
        </div>
      )}
      </div>

      <p className="foot small home__foot">
        <strong>
          {NOT_DIAGNOSIS} {HOME.fictional}
        </strong>{" "}
        Skin measurements by YouCam AI Skin Analysis.
      </p>
    </div>
  );
}
