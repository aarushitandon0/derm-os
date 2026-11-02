import type { ReactNode } from "react";
import { Loading, Notice, Wordmark } from "./components/ui";
import { TabBar, type Tab } from "./components/TabBar";
import { useRoute } from "./router";
import { GuideBar } from "./components/Guide";
import { Waking } from "./components/Waking";
import Demo from "./screens/Demo";
import Basket from "./screens/Basket";
import Brief from "./screens/Brief";
import Capture from "./screens/Capture";
import Checkin from "./screens/Checkin";
import Compare from "./screens/Compare";
import History from "./screens/History";
import Home from "./screens/Home";
import Intent from "./screens/Intent";
import Learn from "./screens/Learn";
import Progress from "./screens/Progress";
import Results from "./screens/Results";
import Routine from "./screens/Routine";
import Shelf from "./screens/Shelf";
import Store from "./screens/Store";
import Trial from "./screens/Trial";
import { useStore } from "./store";

export default function App() {
  const { ready, error, unreachable, health } = useStore();
  const { path, query } = useRoute();

  if (!ready)
    return (
      <div className="app">
        <div className="page page--center">
          <Wordmark size="lg" />
          <Loading />
        </div>
      </div>
    );
  if (error && unreachable) return <Waking />;
  if (error)
    return (
      <div className="app">
        <div className="page page--center">
          <Wordmark size="lg" />
          <Notice tone="stop">{error}</Notice>
        </div>
      </div>
    );

  const [a, b] = path;
  // tab: which tab is highlighted; null = bar shown, nothing highlighted; "none" = no bar (focused flows).
  let screen: ReactNode;
  let tab: Tab | "none" = null;
  switch (a) {
    // Strategy v2: "/" is always the v2 home. It used to show the v1 welcome screen to anyone
    // without a saved "onboarded" flag, which is every first-time visitor (and every judge).
    case undefined:
    case "welcome": // older links
      screen = <Home />;
      tab = "home";
      break;
    case "start":
      screen = <Intent />;
      tab = "none";
      break;
    // Start here: the beginner path (STRATEGY section 4, "Start here"), on the Intent screen.
    case "start-here":
      screen = <Intent beginner />;
      tab = "none";
      break;
    // Strategy v2, the hero flow: build my basket from my face.
    case "basket":
      screen = <Basket autoDemo={query.get("demo")} />;
      tab = "none";
      break;
    // Moment 1: the sale page, and a product's check opened in place.
    case "store":
      screen = <Store checkId={b ?? null} key={b ?? "list"} />;
      tab = "none";
      break;
    // Moment 2: after a breakout, on the Checkin screen with no trial attached.
    case "breakout":
      screen = <Checkin key="breakout" />;
      tab = "none";
      break;
    case "demo":
      screen = <Demo step={Number(b ?? 0)} key={b ?? "0"} />;
      tab = "none";
      break;
    case "progress":
      screen = <Progress trialId={query.get("trial")} key={query.get("trial") ?? "active"} />;
      tab = "progress";
      break;
    case "routine":
      screen = <Routine />;
      tab = "routine";
      break;
    case "learn":
      screen = <Learn section={query.get("section")} />;
      tab = "learn";
      break;
    case "shelf":
      screen = <Shelf />;
      break;
    case "history":
      screen = <History />;
      break;
    case "compare":
      screen = <Compare initial={{ a: query.get("a"), b: query.get("b") }} />;
      break;
    case "capture":
      screen = (
        <Capture
          key={`${query.get("mode")}-${query.get("trial")}`}
          phase={query.get("mode") === "checkin" ? "checkin" : "baseline"}
          trialId={query.get("trial") ?? undefined}
        />
      );
      tab = "none";
      break;
    case "checkin":
      screen = <Checkin id={b} key={b} />;
      tab = "none";
      break;
    case "trial":
      screen = <Trial id={b} key={b} />;
      tab = "routine";
      break;
    case "results":
    case "evidence": // older links
      screen = <Results id={b} key={b} tab={query.get("tab")} />;
      break;
    case "brief":
      screen = <Brief id={b} key={b ?? "latest"} />;
      break;
    default:
      screen = <Home />;
      tab = "home";
  }

  return (
    <div className={`app${tab === "none" ? "" : " app--tabbed"}`}>
      {health?.demo_mode && (
        <p className="demoflag" role="note">
          Prepared demo data · all products are fictional
        </p>
      )}
      <GuideBar path={path} />
      {screen}
      {tab !== "none" && <TabBar active={tab} />}
    </div>
  );
}
