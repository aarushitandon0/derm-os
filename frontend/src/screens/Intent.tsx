import { useState } from "react";
import { Btn, NavBar, PageHead, RowLink } from "../components/ui";
import type { IconName } from "../components/Icon";
import { KEYS, writeLocal } from "../local";
import { go } from "../router";
import { useStore } from "../store";

type Choice = "review" | "start" | "compare" | "brief";

// Each choice opens one of the app's entrances.
export default function Intent() {
  const { activeTrial, trials, shelf } = useStore();
  const [pick, setPick] = useState<Choice | null>(null);
  const latest = activeTrial ?? trials[trials.length - 1] ?? null;

  const options: { id: Choice; icon: IconName; title: string; sub: string }[] = [
    { id: "review", icon: "progress", title: "Track progress", sub: "See real changes over time" },
    { id: "start", icon: "search", title: "Understand my skin", sub: "Start with your routine and history" },
    { id: "compare", icon: "routine", title: "Plan a routine", sub: "Make one change at a time" },
    { id: "brief", icon: "file", title: "Prepare for a dermatologist visit", sub: "Get a clear, concise brief" },
  ];

  const target = (c: Choice) => {
    if (c === "review") return "/progress";
    if (c === "start") return shelf.length ? "/history" : "/shelf";
    if (c === "compare") return "/compare";
    return latest ? `/brief/${latest.id}` : "/brief";
  };

  const go2 = () => {
    if (!pick) return;
    writeLocal(KEYS.onboarded, true);
    go(target(pick));
  };

  return (
    <div className="page page--flow">
      <NavBar back="/welcome" center={<span className="stepbar" role="progressbar" aria-label="Setup" aria-valuemin={1} aria-valuemax={2} aria-valuenow={1}><span /></span>} />
      <PageHead title="What brings you here?" lede="We'll tailor your experience." />
      <div className="choices" role="radiogroup" aria-label="What brings you here?">
        {options.map((o) => (
          <RowLink
            key={o.id}
            radio
            icon={o.icon}
            title={o.title}
            sub={o.sub}
            selected={pick === o.id}
            onClick={() => setPick(o.id)}
            trailing={<span className="radio" aria-hidden />}
          />
        ))}
      </div>
      <div className="flow__foot">
        <Btn onClick={go2} disabled={!pick} wide>
          Continue
        </Btn>
        <button
          type="button"
          className="textbtn textbtn--center"
          onClick={() => {
            writeLocal(KEYS.onboarded, true);
            go("/");
          }}
        >
          Skip for now
        </button>
      </div>
    </div>
  );
}
