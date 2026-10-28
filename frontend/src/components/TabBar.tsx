import { href } from "../router";
import { useStore } from "../store";
import { Icon, type IconName } from "./Icon";

export type Tab = "home" | "progress" | "routine" | "learn" | null;

const TABS: { id: Exclude<Tab, null>; label: string; icon: IconName; to: string }[] = [
  { id: "home", label: "Home", icon: "home", to: "/" },
  { id: "progress", label: "Progress", icon: "progress", to: "/progress" },
  { id: "routine", label: "Routine", icon: "routine", to: "/routine" },
  { id: "learn", label: "Learn", icon: "learn", to: "/learn" },
];

/** Where "+" goes: finish the baseline, then check in; with no trial, plan one first. */
export function plusTarget(trialId: string | undefined, baselineCount: number): { to: string; label: string } {
  if (!trialId) return { to: "/compare", label: "Plan a trial" };
  if (baselineCount < 3) return { to: `/capture?mode=baseline&trial=${trialId}`, label: "Baseline scan" };
  return { to: `/checkin/${trialId}`, label: "New check-in" };
}

export function TabBar({ active }: { active: Tab }) {
  const { activeTrial, activeBaselineCount } = useStore();
  const plus = plusTarget(activeTrial?.id, activeBaselineCount);
  const item = (t: (typeof TABS)[number]) => (
    <a
      key={t.id}
      href={href(t.to)}
      className={`tabbar__item${active === t.id ? " is-on" : ""}`}
      aria-current={active === t.id ? "page" : undefined}
    >
      <Icon name={t.icon} size={22} />
      <span>{t.label}</span>
    </a>
  );
  return (
    <nav className="tabbar no-print" aria-label="Main">
      {item(TABS[0])}
      {item(TABS[1])}
      <a href={href(plus.to)} className="tabbar__plus" aria-label={plus.label}>
        <span className="tabbar__plusbtn">
          <Icon name="plus" size={22} />
        </span>
      </a>
      {item(TABS[2])}
      {item(TABS[3])}
    </nav>
  );
}
