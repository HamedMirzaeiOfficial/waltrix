import { DirectionProvider } from "@radix-ui/react-direction";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { toast } from "@/components/ui/toast";

import { getLang, setLang as applyLang, t, type Lang } from "./i18n";

// Number of mounted operations whose outcome is pending or unknown. Switching language remounts the
// UI, which would drop the "verify with the same idempotency key" state, so it waits for them.
let locks = 0;

/** Blocks language switching while `active` (a money operation is in flight or its outcome unknown). */
export function useLanguageLock(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    locks += 1;
    return () => {
      locks -= 1;
    };
  }, [active]);
}

interface LangValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
}

const LangContext = createContext<LangValue>({ lang: "en", setLang: () => undefined });

/**
 * Holds the UI language. Switching remounts everything below it (key={lang}) so that every t() call
 * runs again, while the React Query cache above it survives, so no data is refetched. Local UI state
 * is reset, which is why useLanguageLock() refuses the switch while a money operation is unresolved.
 * Radix menus, selects and tabs get the direction for RTL keyboard navigation.
 */
export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setState] = useState<Lang>(getLang);
  const setLang = useCallback((next: Lang) => {
    if (locks > 0) {
      toast("warning", t("Finish the current operation first"), t("The language can change once its result is known."));
      return;
    }
    applyLang(next);
    setState(next);
  }, []);
  return (
    <LangContext.Provider value={{ lang, setLang }}>
      <DirectionProvider dir={lang === "fa" ? "rtl" : "ltr"}>
        <LangRoot key={lang}>{children}</LangRoot>
      </DirectionProvider>
    </LangContext.Provider>
  );
}

function LangRoot({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

export function useLang(): LangValue {
  return useContext(LangContext);
}
