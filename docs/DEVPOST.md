# Devpost submission (draft)

Fill in every `[placeholder]` from `backend/results/report.md` and the deploy before submitting.
Keep it to what the build does today.

---

## derm//os

**Same face, same light, one change, honest verdict.**

### Inspiration

You buy a serum, take a selfie two weeks later, and the score is 5 points better. Was that the serum, or the lamp? Skin scores move on their own between two casual photos, and nothing tells you how much. We wanted an app that knows when it can't tell you yet.

### What it does

derm//os turns a skincare purchase into a small, well-run personal experiment:

- **Your own noise range.** Three baseline scans give each concern a range. A check-in counts as a change only when its range doesn't overlap yours.
- **A comparability gate.** Every photo carries its conditions: brightness, light colour, face size, head angle, camera and time of day. If a check-in doesn't match the baseline, derm//os says "can't tell" and shows how to retake, instead of reporting a trend.
- **One change at a time.** Two new leave-on products at once means "can't tell which". A reported reaction such as itching outranks any score.
- **A rebuy line on every verdict:** "The evidence supports rebuying, if you like using it." only when comparable photos leave your range in the better direction; otherwise "Finish the trial before you rebuy", "Can't tell yet, so this isn't a reason to rebuy", or "Don't rebuy".
- **Compare before you buy.** Your history is checked against each option's ingredient list, showing the exact label line. An incomplete label is "unknown", never a pass. "Change nothing" is always a column.
- **A visit brief** for a clinician when something goes wrong.

The strongest thing it ever says is "changed during this trial". It is decision support, not diagnosis.

### The number

[Headline from report.md, e.g. "With nothing changed (n photos of the same face), a fixed ±5-point rule called a change in X% of photo-pair comparisons; derm//os's pre-registered verdict did in Y% of M baseline/check-in splits. Under a warm lamp, the gate marked Z% of pairs not comparable."]

The derm//os number uses the app's own verdict function with its constants fixed before the shoot. The comparisons share photos, so they aren't independent, and the analysis is ours.

### How we built it

- **YouCam AI Skin Analysis v2.1 (SD)**: `POST /s2s/v2.0/file` and a presigned upload, `POST /s2s/v2.1/task/skin-analysis`, polling `GET /s2s/v2.1/task/skin-analysis/{task_id}`, mask download, `POST /s2s/v2.0/task/delete` to remove the photo and outputs at YouCam, and the free `GET /s2s/v1.0/client/credit` and `GET /s2s/v2.0/credit/feature-cost` before every live scan. Decisions use `raw_score`.
- **FastAPI + SQLite** on Python 3.12, in Docker. Every photo is cropped on the server by a local face detector (MediaPipe BlazeFace) so the face is the same width in every scan.
- **React + TypeScript PWA**, phone first, with a live MediaPipe face guide and an auto-shutter.
- **Rules, not a model, decide**: the noise ranges, gate, verdicts, rebuy line and exclusions are plain, tested code.
- **Unit safety**: the public demo replays prepared scores. Live scans need a passcode and stop at 300 units total and 100 a day (then replay prepared data, and say so), with a 200-unit reserve.

### Honesty, engineered

- A **claim linter** in CI fails the build if any screen or template sentence says cause, cure, treat, diagnose, prove, guarantee, clinically, "it works", or claims a percentage improvement.
- A **benchmark** of 115 cases written from the design before running the engine: 115 of 115 pass. We wrote it, so it isn't independent; it tests the rules, not YouCam's accuracy.
- **docs/FACTS.md** links every README claim to the code and the test behind it, and marks the few that aren't automated.
- The guided demo's second persona gets a positive verdict from prepared scores through the real engine, with no special case: the same scores under lamp light are "not comparable".

### Challenges

- Getting the same face size in every photo without upscaling, recolouring or rotating anything.
- Saying "can't tell" often enough to be honest without making the app feel useless.
- Keeping YouCam units safe on a public demo.

### What we learned

[One or two sentences from the shoot, e.g. how big the no-change range was per concern, and what the warm lamp did.]

### What's next

- Real repeat-scan data for the demo personas.
- An optional language layer (already written, off in the deployed app) for typed-in history and plain-language summaries, behind a claim validator. It runs on a local Ollama server with no API key.
- Postgres so trials survive restarts.

### Try it

- App: [Vercel URL] → **Try the 90-second demo** (prepared data, no account)
- Code: https://github.com/aarushitandon0/derm-os
- Video: [YouTube URL]

All products in the app are fictional.
