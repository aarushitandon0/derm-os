-- derm//os migration 001: accounts on Supabase Postgres.
-- Apply from backend/ with:  python -m scripts.migrate   (reads DATABASE_URL; see docs/DEPLOY.md)
--
-- Face photos are never stored: no table has a bytea column or a photo / image / URL column
-- (tests/test_accounts.py checks this file). A scan row holds results only.
-- Row Level Security is ON for every table with NO policies, so the anon and authenticated
-- roles (the browser's Supabase key) can read or write nothing. Only the backend, connecting
-- as the database owner, touches these tables, and it scopes every query by the user id from
-- a verified token.

-- ---------------------------------------------------------------- accounts
CREATE TABLE IF NOT EXISTS profiles (
    user_id      uuid PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
    display_name text NOT NULL DEFAULT '',
    finish_goal  text CHECK (finish_goal IN ('dewy', 'natural', 'matte')),
    budget       text CHECK (budget IN ('under_700', 'under_1000', 'any')),
    beginner     boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scans (
    id               text PRIMARY KEY,
    user_id          uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    created_at       timestamptz NOT NULL DEFAULT now(),
    zone_types       jsonb NOT NULL,          -- {"t_zone": "oily", "cheeks": "normal"}
    concern_values   jsonb NOT NULL,          -- YouCam concern values, never shown as scores
    undertone        text,                    -- warm / neutral / cool / olive ...
    undertone_method text,                    -- "worked out from your skin colour" / "from your answers"
    engine_versions  jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS scans_user ON scans (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_history (
    id                  text PRIMARY KEY,
    user_id             uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    kind                text NOT NULL CHECK (kind IN ('chip', 'record')),  -- ingredient chip / product-level record
    body                jsonb NOT NULL,
    clinician_confirmed boolean NOT NULL DEFAULT false,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS user_history_user ON user_history (user_id, kind);

CREATE TABLE IF NOT EXISTS user_shelf (
    user_id     uuid PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
    product_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_baskets (
    id              text PRIMARY KEY,
    user_id         uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    created_at      timestamptz NOT NULL DEFAULT now(),
    demo            boolean NOT NULL DEFAULT false,  -- a prepared demo basket, labelled as such
    basket          jsonb NOT NULL,                  -- results only: no try-on images, masks or links
    start_plan      jsonb,
    engine_versions jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS user_baskets_user ON user_baskets (user_id, created_at DESC);

-- ---------------------------------------------------------------- unchanged from SQLite
-- Live YouCam units spent through this server (judge caps), moved as-is.
CREATE TABLE IF NOT EXISTS spend (id text PRIMARY KEY, day text, units real, state text, at text);

-- Guest / demo tables (one JSON body per row), same shape as the SQLite file. Never hold account data.
CREATE TABLE IF NOT EXISTS history  (id text PRIMARY KEY, body text, created text);
CREATE TABLE IF NOT EXISTS shelf    (id text PRIMARY KEY, body text, created text);
CREATE TABLE IF NOT EXISTS captures (id text PRIMARY KEY, body text, created text);
CREATE TABLE IF NOT EXISTS trials   (id text PRIMARY KEY, body text, created text);
CREATE TABLE IF NOT EXISTS outcomes (id text PRIMARY KEY, body text, created text);
CREATE TABLE IF NOT EXISTS baskets  (id text PRIMARY KEY, body text, created text);
CREATE TABLE IF NOT EXISTS chips    (id text PRIMARY KEY, body text, created text);

-- ---------------------------------------------------------------- Row Level Security
-- On, with no policies: the browser's anon / authenticated roles get nothing.
ALTER TABLE profiles     ENABLE ROW LEVEL SECURITY;
ALTER TABLE scans        ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_shelf   ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_baskets ENABLE ROW LEVEL SECURITY;
ALTER TABLE spend        ENABLE ROW LEVEL SECURITY;
ALTER TABLE history      ENABLE ROW LEVEL SECURITY;
ALTER TABLE shelf        ENABLE ROW LEVEL SECURITY;
ALTER TABLE captures     ENABLE ROW LEVEL SECURITY;
ALTER TABLE trials       ENABLE ROW LEVEL SECURITY;
ALTER TABLE outcomes     ENABLE ROW LEVEL SECURITY;
ALTER TABLE baskets      ENABLE ROW LEVEL SECURITY;
ALTER TABLE chips        ENABLE ROW LEVEL SECURITY;

-- Belt and braces: the API roles have no table privileges here either.
REVOKE ALL ON profiles, scans, user_history, user_shelf, user_baskets, spend,
              history, shelf, captures, trials, outcomes, baskets, chips
       FROM anon, authenticated;
