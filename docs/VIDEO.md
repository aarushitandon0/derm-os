# derm//os: 3-minute video shot list

Record on a phone (screen recording) plus a few seconds of a laptop for the code. Each shot is
marked **LIVE** (a real YouCam scan on the phone, with the passcode, spending units) or
**PREPARED** (demo mode; the screen says "Prepared demo data"). Say "prepared data" aloud whenever
a prepared screen is on.

Rules for the cut:

- No real brands, products, shops or logos anywhere in frame (all products in the app are fictional). Check the background of the live shot.
- No music you don't own. Use silence, your voice, or a track you made or one licensed for reuse; keep its licence link in the Devpost text.
- Don't name or show any other hackathon entry.
- Fill in every `[placeholder]` from `backend/results/report.md` before recording. Say numbers exactly as measured, with n.

| Time | Shot | Source | Voice-over (read as written) |
| --- | --- | --- | --- |
| 0:00–0:20 | Black screen, then the headline sentence typed on screen; cut to the two lamp-vs-window photos' scores side by side (numbers only, no face) | Results of the shoot | "We scanned the same face [n] times with nothing changed. A fixed five-point rule called a change in [X]% of comparisons. derm//os called one in [Y]% of [M] baseline-and-check-in splits, and its rule was fixed before we looked. Under a warm lamp, it marked [Z]% of photo pairs not comparable." |
| 0:20–0:35 | Landing page: "Same face, same light, one change, honest verdict." | PREPARED | "derm//os is for one question: before you rebuy a skincare product, did your skin change more than it does on its own?" |
| 0:35–0:55 | Live baseline on the phone: the face guide turns green, the auto-shutter takes 3 photos, "Analysing" steps | **LIVE** | "This is a live scan with YouCam AI Skin Analysis version 2.1. The server crops the photo around the face so the face is the same size every time, uploads it with `POST /s2s/v2.0/file` and a presigned PUT, creates the task with `POST /s2s/v2.1/task/skin-analysis`, and polls `GET /s2s/v2.1/task/skin-analysis/{task_id}`. Three scans give a range, not a single number." |
| 0:55–1:05 | Capture-quality screen after the live scan | **LIVE** | "It saves the marked-area masks straight away because the links expire, then deletes the task and the photo at YouCam with `POST /s2s/v2.0/task/delete`. Before every live scan it reads the balance with `GET /s2s/v1.0/client/credit` and the exact price from `GET /s2s/v2.0/credit/feature-cost`." |
| 1:05–1:15 | Tap "Try the 90-second demo" → step list | PREPARED | "From here it's prepared data, so judges can try it without units. Every verdict is still worked out by the same engine." |
| 1:15–1:30 | Step 1, History: reaction to the fragranced moisturiser; "avoid fragrance" as a separate record | PREPARED | "Riya once reacted to a fragranced moisturiser. That's a reaction to one product. Avoiding fragrance is her own choice, and the app keeps the two apart." |
| 1:30–1:50 | Step 2, Compare: Option A blocked with the label line; Option B "Unknown, not a pass"; tap Replaces | PREPARED | "Two sale options. One is blocked, and you can see the exact line on the label. The other's ingredient list is incomplete, so it says unknown, never a pass. And changing nothing is always a column." |
| 1:50–2:05 | Steps 3–4: trial card, then the warm-lamp check-in, "Not comparable" and the retake fix | PREPARED | "She tries one product and holds everything else fixed. Then she checks in under a warm lamp. The gate says these photos can't be compared, and tells her how to retake." |
| 2:05–2:20 | Step 5: day 14, "No detectable change yet", rebuy line | PREPARED | "Back in window light at day 14: her new scores sit inside her own range. Rebuy? Finish the trial first." |
| 2:20–2:35 | Steps 6–7: itching logged → Stop card → visit brief | PREPARED | "Then she logs itching. A reaction you can feel outranks any score: don't rebuy, and here's a one-page brief for a clinician." |
| 2:35–2:45 | Step 8: Meera, "Redness dropped beyond your usual variation during this trial", rebuy line | PREPARED | "Meera's check-ins match her baseline and leave her range. That's the strongest thing derm//os will say: it changed during this trial, not why." |
| 2:45–3:00 | Laptop: `docs/architecture.svg`, then CI green, benchmark "115 / 115", claim linter "0 findings" | Repo | "Rules decide; YouCam measures. A benchmark we wrote ourselves passes 115 of 115, a claim linter blocks overclaiming words in every screen, and every claim in the README links to the test behind it. Decision support, not diagnosis." |

Before you publish: watch it once with the sound off and check every prepared screen shows "Prepared demo data".
