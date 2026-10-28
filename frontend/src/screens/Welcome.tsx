import { Btn, Wordmark } from "../components/ui";
import { NOT_DIAGNOSIS } from "../copy";

// The hero is one replaceable file in frontend/public. Swap in your own image
// (any format) and update this path if the name changes.
export const WELCOME_HERO = "/welcome-hero.svg";

export default function Welcome() {
  return (
    <div className="welcome">
      <img className="welcome__hero" src={WELCOME_HERO} alt="" aria-hidden />
      <div className="welcome__top">
        <h1 className="welcome__mark">
          <Wordmark size="xl" />
        </h1>
        <p className="welcome__tag">Same face, same light, one change, honest verdict.</p>
        <p className="welcome__sub">
          Before you rebuy a skincare product, find out whether your skin changed more than it does on its own.
        </p>
      </div>
      <div className="welcome__bottom">
        <Btn to="/demo" wide icon="arrow">
          Try the 90-second demo
        </Btn>
        <Btn to="/start" kind="ghost" wide>
          Start my own trial
        </Btn>
        <p className="welcome__note">{NOT_DIAGNOSIS} No account needed. All products are fictional.</p>
      </div>
    </div>
  );
}
