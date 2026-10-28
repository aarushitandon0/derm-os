import { useEffect, useState } from "react";
import { KEYS, readLocal, writeLocal } from "../local";

/** Personal notes for one trial, kept on this device. The visit brief prints the same notes. */
export function useTrialNotes(trialId: string): [string, (v: string) => void] {
  const [notes, setNotes] = useState(() => readLocal<string>(KEYS.notes(trialId), ""));
  useEffect(() => setNotes(readLocal<string>(KEYS.notes(trialId), "")), [trialId]);
  const update = (v: string) => {
    setNotes(v);
    writeLocal(KEYS.notes(trialId), v);
  };
  return [notes, update];
}

export function TrialNotes({ trialId, placeholder = "Add a note…" }: { trialId: string; placeholder?: string }) {
  const [notes, setNotes] = useTrialNotes(trialId);
  return (
    <label className="notes">
      <span className="sr-only">Notes</span>
      <textarea
        className="notes__input"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder={placeholder}
        rows={3}
      />
      <span className="notes__hint">Saved on this device. Included in your visit brief.</span>
    </label>
  );
}
