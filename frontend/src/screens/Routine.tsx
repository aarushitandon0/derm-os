import { useState } from "react";
import type { Role } from "../api";
import { addDays, concernLabel, fmtLong, localISODate, ROLE_LABEL } from "../copy";
import { Icon } from "../components/Icon";
import { ProductArt } from "../components/ProductArt";
import { Btn, NavBar, PageHead, RowLink, Section, Segmented, TabPanel } from "../components/ui";
import { KEYS, readLocal, writeLocal } from "../local";
import { href } from "../router";
import { useStore } from "../store";

const ORDER: Role[] = ["cleanser", "toner", "serum", "treatment", "moisturiser", "sunscreen"];

export default function Routine() {
  const { activeTrial: t, catalog, shelf, activeBaselineCount } = useStore();
  const [tab, setTab] = useState<"overview" | "schedule">("overview");
  const today = localISODate();
  const [ticks, setTicks] = useState<string[]>(() => readLocal<string[]>(KEYS.ticks(today), []));

  const product = t ? catalog[t.product_id] : undefined;
  const items = [...new Set([...shelf, ...(t ? [t.product_id] : [])])]
    .map((id) => catalog[id])
    .filter(Boolean)
    .sort((a, b) => ORDER.indexOf(a.role) - ORDER.indexOf(b.role));

  const toggle = (id: string) => {
    const next = ticks.includes(id) ? ticks.filter((x) => x !== id) : [...ticks, id];
    setTicks(next);
    writeLocal(KEYS.ticks(today), next);
  };

  return (
    <div className="page">
      <NavBar
        right={
          <a className="iconbtn" href={href("/shelf")} aria-label="Edit your routine">
            <Icon name="plus" />
          </a>
        }
      />
      <PageHead title="Your routine" lede="One change at a time, everything else held steady." />
      <Segmented
        idBase="routine"
        label="Routine sections"
        value={tab}
        onChange={setTab}
        options={[
          { value: "overview", label: "Overview" },
          { value: "schedule", label: "Schedule" },
        ]}
      />

      {tab === "overview" && (
        <TabPanel idBase="routine" value="overview">
          <Section label="Current experiment">
            {t && product ? (
              <RowLink
                to={`/trial/${t.id}`}
                icon={<ProductArt product={product} size={34} />}
                title={product.name}
                sub={`Started ${fmtLong(t.started_at)} · ${concernLabel(t.goal_concern)}`}
              />
            ) : (
              <div className="empty empty--inline">
                <p>No experiment running. Compare options, then try one change.</p>
                <Btn kind="ghost" to="/compare" wide>
                  Plan a routine
                </Btn>
              </div>
            )}
          </Section>

          <Section label="Today">
            {items.length ? (
              <ul className="checklist">
                {items.map((p) => {
                  const on = ticks.includes(p.id);
                  return (
                    <li key={p.id}>
                      <button type="button" className={`tick${on ? " is-on" : ""}`} role="checkbox" aria-checked={on} onClick={() => toggle(p.id)}>
                        <span className="tick__box" aria-hidden>
                          {on && <Icon name="check" size={14} />}
                        </span>
                        <span className="tick__body">
                          <span className="tick__name">{p.name}</span>
                          <span className="tick__role">
                            {ROLE_LABEL[p.role]}
                            {t?.product_id === p.id ? " · under trial" : ""}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <div className="empty empty--inline">
                <p>Your shelf is empty.</p>
                <Btn kind="ghost" to="/shelf" wide>
                  Add what you use now
                </Btn>
              </div>
            )}
            {items.length > 0 && <p className="small muted">Ticks are saved on this device for today only.</p>}
          </Section>

          <Section label="More">
            <div className="rows">
              <RowLink to="/shelf" icon="routine" title="Shelf" sub="The products in your routine" />
              <RowLink to="/history" icon="history" title="History" sub="Reactions, avoided and confirmed ingredients" />
              <RowLink to="/compare" icon="compare" title="Compare options" sub="Change nothing, Option A or Option B" />
            </div>
          </Section>
        </TabPanel>
      )}

      {tab === "schedule" && (
        <TabPanel idBase="routine" value="schedule">
          {t ? (
            <>
              <Section label="Check-ins">
                <ol className="schedule">
                  <li className={activeBaselineCount >= 3 ? "is-done" : "is-due"}>
                    <span className="schedule__day">Day 0</span>
                    <span className="schedule__what">
                      Baseline, 3 photos
                      <span className="schedule__sub">
                        {activeBaselineCount >= 3 ? "Done" : `${activeBaselineCount} of 3 done`}
                      </span>
                    </span>
                  </li>
                  {t.checkpoints_days.map((d) => {
                    const date = addDays(t.started_at, d);
                    const due = Date.now() >= date.getTime();
                    return (
                      <li key={d} className={due ? "is-due" : ""}>
                        <span className="schedule__day">Day {d}</span>
                        <span className="schedule__what">
                          Check-in, 2 photos
                          <span className="schedule__sub">
                            {fmtLong(date)}
                            {due ? " · due" : ""}
                          </span>
                        </span>
                      </li>
                    );
                  })}
                </ol>
              </Section>
              <Section label="Holding fixed">
                {t.held_fixed.length ? (
                  <ul className="plainlist">
                    {t.held_fixed.map((h) => (
                      <li key={h}>{catalog[h]?.name ?? h}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">Everything else in your routine.</p>
                )}
              </Section>
              <Btn kind="ghost" to={`/trial/${t.id}`} wide>
                Trial details and reminders
              </Btn>
            </>
          ) : (
            <div className="empty empty--inline">
              <p>A schedule appears once a trial is running.</p>
              <Btn kind="ghost" to="/compare" wide>
                Plan a routine
              </Btn>
            </div>
          )}
        </TabPanel>
      )}
    </div>
  );
}
