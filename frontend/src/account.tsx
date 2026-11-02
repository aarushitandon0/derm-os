import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Session, SupabaseClient } from "@supabase/supabase-js";

// Accounts (Supabase Auth, email + password). Optional: with VITE_SUPABASE_URL or
// VITE_SUPABASE_ANON_KEY missing, every login control is hidden, the library is never loaded,
// and the demo works exactly as before. The demo never needs an account.
const URL_ = ((import.meta.env.VITE_SUPABASE_URL as string | undefined) ?? "").trim();
const KEY_ = ((import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined) ?? "").trim();
export const ACCOUNTS_ENABLED = Boolean(URL_ && KEY_);

let clientP: Promise<SupabaseClient> | null = null;
function client(): Promise<SupabaseClient> | null {
  if (!ACCOUNTS_ENABLED) return null;
  clientP ??= import("@supabase/supabase-js").then(({ createClient }) =>
    // PKCE: email links come back as ?code=…, which leaves the app's #/hash routes alone.
    createClient(URL_, KEY_, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, flowType: "pkce" },
    })
  );
  return clientP;
}

interface Account {
  enabled: boolean;
  /** False until the saved session (if any) has been read. */
  ready: boolean;
  session: Session | null;
  email: string | null;
  userId: string | null;
  /** A fresh access token (refreshed by the library), or null when logged out. */
  token: () => Promise<string | null>;
  signUp: (email: string, password: string) => Promise<{ confirm: boolean }>;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  resetPassword: (email: string) => Promise<void>;
  updatePassword: (password: string) => Promise<void>;
  /** Set when the reset-password email link opened the app. */
  recovering: boolean;
}

const Ctx = createContext<Account | null>(null);

export function AccountProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(!ACCOUNTS_ENABLED);
  const [recovering, setRecovering] = useState(false);

  useEffect(() => {
    const p = client();
    if (!p) return;
    let unsub: (() => void) | undefined;
    p.then(async (sb) => {
      const { data } = await sb.auth.getSession();
      setSession(data.session);
      setReady(true);
      const { data: sub } = sb.auth.onAuthStateChange((event, s) => {
        setSession(s);
        if (event === "PASSWORD_RECOVERY") setRecovering(true);
      });
      unsub = () => sub.subscription.unsubscribe();
    }).catch(() => setReady(true)); // library failed to load: behave as logged out, no crash
    return () => unsub?.();
  }, []);

  const need = async () => {
    const p = client();
    if (!p) throw new Error("Accounts aren't set up here.");
    return p;
  };

  const token = useCallback(async () => {
    const p = client();
    if (!p) return null;
    const { data } = await (await p).auth.getSession();
    return data.session?.access_token ?? null;
  }, []);

  const value = useMemo<Account>(
    () => ({
      enabled: ACCOUNTS_ENABLED,
      ready,
      session,
      email: session?.user.email ?? null,
      userId: session?.user.id ?? null,
      token,
      recovering,
      signUp: async (email, password) => {
        const sb = await need();
        const { data, error } = await sb.auth.signUp({
          email,
          password,
          options: { emailRedirectTo: window.location.origin + window.location.pathname },
        });
        if (error) throw new Error(plainAuthError(error.message));
        return { confirm: !data.session };
      },
      signIn: async (email, password) => {
        const sb = await need();
        const { error } = await sb.auth.signInWithPassword({ email, password });
        if (error) throw new Error(plainAuthError(error.message));
      },
      signOut: async () => {
        const sb = await need();
        await sb.auth.signOut();
      },
      resetPassword: async (email) => {
        const sb = await need();
        const { error } = await sb.auth.resetPasswordForEmail(email, {
          redirectTo: window.location.origin + window.location.pathname,
        });
        if (error) throw new Error(plainAuthError(error.message));
      },
      updatePassword: async (password) => {
        const sb = await need();
        const { error } = await sb.auth.updateUser({ password });
        if (error) throw new Error(plainAuthError(error.message));
        setRecovering(false);
      },
    }),
    [ready, session, token, recovering]
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAccount(): Account {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAccount outside AccountProvider");
  return v;
}

function plainAuthError(m: string): string {
  if (/invalid login credentials/i.test(m)) return "That email and password don't match an account.";
  if (/email not confirmed/i.test(m)) return "Confirm your email first: open the link we sent you.";
  if (/already registered|already been registered/i.test(m)) return "There's already an account with that email. Log in instead.";
  if (/password should be|at least/i.test(m)) return "Use a password of at least 8 characters.";
  if (/rate limit|too many/i.test(m)) return "Too many tries. Wait a minute, then try again.";
  if (/fetch|network/i.test(m)) return "Can't reach the sign-in service. Check your connection and try again.";
  return m;
}
