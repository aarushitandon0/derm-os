import { useEffect, useState } from "react";
import { useStore } from "../store";
import { Btn, Wordmark } from "./ui";

const RETRY_MS = 6000;
const MAX_AUTO = 15; // about 90 seconds of automatic retries

// A free host puts the server to sleep when idle; the first request wakes it.
export function Waking() {
  const { refresh } = useStore();
  const [tries, setTries] = useState(0);
  const [busy, setBusy] = useState(false);

  const retry = async () => {
    setBusy(true);
    await refresh();
    setBusy(false);
    setTries((n) => n + 1);
  };

  useEffect(() => {
    if (tries >= MAX_AUTO) return;
    const t = window.setTimeout(retry, RETRY_MS);
    return () => window.clearTimeout(t);
  }, [tries]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="app">
      <div className="page page--center waking" role="status" aria-live="polite">
        <Wordmark size="lg" />
        <p className="waking__head">Waking the server, about 30 seconds</p>
        <p className="small muted">
          {tries < MAX_AUTO
            ? "The demo server sleeps when nobody is using it. This page retries on its own."
            : "Still asleep. Try again, or come back in a minute."}
        </p>
        <span className="loading__dot" aria-hidden />
        <Btn kind="ghost" onClick={retry} disabled={busy}>
          {busy ? "Trying…" : "Retry now"}
        </Btn>
      </div>
    </div>
  );
}
