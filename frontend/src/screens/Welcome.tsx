import { Btn, Wordmark } from "../components/ui";

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
        <p className="welcome__tag">
          Real changes.
          <br />
          Backed by evidence.
        </p>
      </div>
      <div className="welcome__bottom">
        <Btn to="/start" wide icon="arrow">
          Get started
        </Btn>
        <p className="welcome__note">Decision support, not a diagnosis. No account needed.</p>
      </div>
    </div>
  );
}
