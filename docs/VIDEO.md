# derm//os: video shot list (2:50 max)

Screen-record on a phone, on the **live deployed app** (the Vercel URL), not localhost. Speak over it; no music.

## Before you record

- **Only fictional brands in frame.** Everything in the app is fictional. Check the background of the selfie and hide real product bottles, shop names and logos. No other hackathon entry either.
- **The try-on needs one live run.** In demo mode the try-on card says "Preview appears on a live scan". To show your own face in matte and dewy:
  - set `DEMO_MODE=0` on Render and enter the passcode on the phone;
  - one live basket costs 34 units (Skin Tone 20 + Skin Analysis 12 + 2 try-on renders);
  - run it only with an approved unit budget, then set `DEMO_MODE` back to `1`.
- **Prepared screens are labelled.** Every other beat can use **Use Riya's demo face** (demo data, 0 units). Say "demo data" aloud whenever its tag is on screen.
- **Free wake-up.** The free Render server sleeps. Open the app once a minute before you record.

## Shots

| Time | Shot (phone screen) | Voice-over |
| --- | --- | --- |
| 0:00–0:15 | Your face, then Home: **Build my basket from my face** | "Vitamin C made me itch. Azelaic acid broke me out. There's a sale on, everyone's buying the trending serum, and opened skincare can't be returned. So I built derm//os: shop by your face, not by the hype." |
| 0:15–0:40 | Selfie with the live face guide → the face map: zones in colour, "T-zone: oily", "Cheeks: …", needs, undertone | "One selfie. YouCam Skin Analysis reads my skin type zone by zone, so my oily T-zone and my cheeks get different products. YouCam Skin Tone gives my skin colour, and derm//os works out my undertone from it with a written rule. No scores, just words." |
| 0:40–0:55 | The questions: finish (dewy), then the history chips: tap **Vitamin C → itched**, **Azelaic acid → broke me out** | "I pick the finish I want and tap what's bothered me before. Most people remember the ingredient, not the label." |
| 0:55–1:30 | The basket: scroll the cards (T-zone gel, cheek cream, tint in my shade, with Why · How to use), then **Skipped**: Dewdrop Skin Tint "Contains Alcohol Denat., in 2 of 2 products that made you itch…", Bright Dew C Gel (vitamin C family), Dew Veil "Ingredient list incomplete → unknown"; then "You already own" the cleanser | "One card per job, each with three reasons: from my face, from my history, and my finish. And here's what it skipped, with the exact reason: this tint has Alcohol Denat., which was in both products that made me itch. This gel has a vitamin C cousin. This one's ingredient list is incomplete, so it's unknown, never a pass. And I already own a cleanser, so it tells me not to buy another." |
| 1:30–1:45 | Start plan: patch test, then the three dates two weeks apart; tap one calendar reminder | "Then a start plan: patch-test first, one new product every two weeks, gentlest first, with reminders." |
| 1:45–2:05 | **See the finish on you**: matte vs dewy on your face, in your shade | "And before I pay: YouCam Makeup Try-On puts the tint on my own photo, matte versus dewy, in my shade." |
| 2:05–2:20 | Paste a label: paste an ingredient list from another shop → the result with its labelled sources | "Found something in another shop? Paste its ingredient list. It's checked against my history the same way." |
| 2:20–2:30 | Home → **My skin just broke out** → What changed? → the result | "And if I break out anyway, the breakout helper looks at what changed two to eight weeks ago and says which one product to pause." |
| 2:30–2:50 | Back to the basket, then the end card: app URL, repo, "Skin Analysis · Skin Tone · Makeup Try-On" | "A chatbot guesses. derm//os measures your face, checks real ingredient lists against your history, and shows you the finish on you. Built on three YouCam APIs: Skin Analysis, Skin Tone and Makeup Virtual Try-On. Decision support, not a diagnosis." |

## Before you publish

- Watch it once with the sound off: no real brand in frame, and the demo-data tag is visible on every prepared screen.
- Check it runs 2:50 or less.
- Put the link in the README's "Judge quick access" table and in docs/DEVPOST.md.
