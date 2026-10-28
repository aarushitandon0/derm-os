import { useState } from "react";
import { api, ApiError, type Reaction } from "../api";
import { fmtDate, fmtLong, localISODate, REACTION_RULE, symptomLabel } from "../copy";
import { Btn } from "./ui";
import { Icon } from "./Icon";

const andList = (xs: string[]) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

/** Stop card shown while any reaction is unresolved. Symptoms outrank scores. */
export function StopCard({
  trialId,
  productName,
  reactions,
  onChanged,
}: {
  trialId: string;
  productName: string;
  reactions: Reaction[];
  onChanged: () => void;
}) {
  const open = reactions.filter((r) => !r.resolved);
  if (!open.length) return null;
  return (
    <section className="stopcard" aria-labelledby="stopcard-title">
      <p className="stopcard__kicker">
        <Icon name="alert" size={18} /> Stop
      </p>
      <h2 id="stopcard-title" className="stopcard__title">
        Pause {productName}.
      </h2>
      <p className="stopcard__text">
        You reported {andList(open.map((r) => symptomLabel(r.symptom).toLowerCase()))}. A reaction you can feel
        outranks any score. If it's severe or getting worse, see a clinician.
      </p>
      <p className="stopcard__rule">{REACTION_RULE}</p>
      <ReactionList trialId={trialId} reactions={open} onChanged={onChanged} />
      <Btn kind="ghost" to={`/brief/${trialId}`} wide icon="file">
        Visit brief
      </Btn>
    </section>
  );
}

export function ReactionList({
  trialId,
  reactions,
  onChanged,
}: {
  trialId: string;
  reactions: Reaction[];
  onChanged: () => void;
}) {
  if (!reactions.length) return <p className="muted">No reactions reported in this trial.</p>;
  return (
    <ul className="reactions">
      {reactions.map((r) => (
        <ReactionItem key={r.id} trialId={trialId} r={r} onChanged={onChanged} />
      ))}
    </ul>
  );
}

function ReactionItem({ trialId, r, onChanged }: { trialId: string; r: Reaction; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [date, setDate] = useState(localISODate());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const min = localISODate(new Date(r.logged_at));

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.resolveReaction(trialId, r.id, { resolved_on: date || undefined, note });
      setOpen(false);
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className={`reaction${r.resolved ? " is-resolved" : ""}`}>
      <div className="reaction__head">
        <span className="reaction__name">{symptomLabel(r.symptom)}</span>
        <span className="reaction__state">{r.resolved ? "Resolved" : "In force"}</span>
      </div>
      <p className="reaction__meta">
        Reported {fmtDate(r.logged_at)}
        {r.last_logged_at !== r.logged_at && `, again ${fmtDate(r.last_logged_at)}`}
        {r.resolved && r.resolved_on && ` · resolved ${fmtLong(r.resolved_on + "T12:00:00")}`}
      </p>
      {r.resolution_note && <p className="reaction__note">{r.resolution_note}</p>}
      {!r.resolved &&
        (open ? (
          <div className="reaction__form">
            <label className="field">
              <span>Resolved on</span>
              <input type="date" value={date} min={min} max={localISODate()} onChange={(e) => setDate(e.target.value)} />
            </label>
            <label className="field">
              <span>Note (optional)</span>
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Settled 3 days after pausing" />
            </label>
            {err && <p className="cell-note cell-note--stop">{err}</p>}
            <div className="btnrow">
              <Btn onClick={save} disabled={busy}>
                {busy ? "Saving…" : "Mark resolved"}
              </Btn>
              <Btn kind="quiet" onClick={() => setOpen(false)}>
                Cancel
              </Btn>
            </div>
          </div>
        ) : (
          <button type="button" className="textbtn" onClick={() => setOpen(true)}>
            Mark resolved
          </button>
        ))}
    </li>
  );
}
