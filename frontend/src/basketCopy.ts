// Copy for the basket flow (docs/strategy.md sections 4 and 9). The claim linter holds this file
// to the shopping-flow rules too: plain words only, and every step gives an answer.
export const BASKET = {
  hero: "Build my basket from my face",
  heroSub: "One selfie, three questions, and a basket from this shop's stock made for your face.",
  usp: "Shop by your face, not by the hype.",
  startTitle: "Start with your face",
  demoFace: "Use Riya's demo face",
  demoFaceSub: "Combination skin, warm-neutral, wants a dewy finish. Her history is already saved.",
  demoNote: "Demo mode: a prepared face is used, never your photo, and nothing is sent to YouCam.",
  selfie: "Use my selfie",
  selfieSub: "One photo, facing a window, no filters.",
  questionsTitle: "Three quick questions",
  build: "Build my basket",
  building: "Building your basket…",
  faceMapLabel: "Your face map",
  findingsLabel: "What your scan found",
  findingsWhy: "why your basket aims at",
  findingsDrives: "adds",
  basketLabel: "Your basket",
  skippedLabel: "Skipped",
  ownLabel: "You already own",
  nextLabel: "Your next step",
  tryonButton: "See the finish on you",
  tryonTitle: "Matte or dewy, on you",
  tryonLede: "Your base product in your shade, two ways, side by side.",
  tryonPending: "Preview appears on a live scan",
  backToBasket: "Back to my basket",
  beginnerFace: "Use a beginner demo face",
  beginnerFaceSub: "Normal skin, nothing tried yet. Starts from a cleared demo history.",
  chipsHelp: "Most people remember the ingredient, not the label. Tap one, then say what happened. Saved as you go.",
  beginnerHelp: "No history step: your basket leans to gentle, fragrance-free products with few actives.",
  pasteLabel: "Check any product",
  pasteHelp: "Found something in another shop? Paste its ingredient list and it is checked like this shop's stock.",
  storeLink: "Browse the whole sale",
  total: "New spend",
  alsoFits: "Also fits",
  patchFirst: "patch-test first",
  howLabel: "How to use",
  whyLabel: "Why",
};

export const ZONE_COLOUR: Record<string, string> = {
  oily: "#d9a441",
  dry: "#7fa3c2",
  normal: "#8fb08f",
};

export const ZONE_WORD: Record<string, string> = {
  oily: "oily: shine through the day",
  dry: "dry: tight, needs water",
  normal: "normal: comfortable",
};

// The face map's colour key, in words (no numbers).
export const ZONE_KEY: { type: string; word: string }[] = [
  { type: "oily", word: "amber: oily" },
  { type: "dry", word: "blue: dry" },
  { type: "normal", word: "sage: normal" },
];

// The v2 home (docs/strategy.md section 4).
export const HOME = {
  lede: "One selfie becomes a skincare basket from this shop's stock: read zone by zone, matched to the finish you want, in your undertone, minus what bothered you before.",
  tryLabel: "No selfie handy? Try it on a prepared face",
  riya: "Use Riya's demo face",
  riyaSub: "Combination skin, history saved",
  beginner: "Use a beginner demo face",
  beginnerSub: "Nothing tried yet",
  otherLabel: "Or start somewhere else",
  storeLink: "Check one product from the sale",
  fictional: "All products are fictional.",
  artCaption: "Face map, zone by zone, then a basket from the shelf",
};
