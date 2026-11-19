import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { setLang as resetLang, t } from "./i18n";
import { LangProvider, useLanguageLock, useLang } from "./lang";

afterEach(() => resetLang("en"));

function Probe({ locked }: { locked: boolean }) {
  useLanguageLock(locked);
  const { lang, setLang } = useLang();
  return (
    <button onClick={() => setLang(lang === "en" ? "fa" : "en")}>
      {lang}:{t("Overview")}
    </button>
  );
}

describe("LangProvider", () => {
  it("switches language and re-renders translated text", () => {
    render(
      <LangProvider>
        <Probe locked={false} />
      </LangProvider>,
    );
    expect(screen.getByRole("button").textContent).toBe("en:Overview");
    act(() => screen.getByRole("button").click());
    expect(screen.getByRole("button").textContent).toBe("fa:نمای کلی");
    expect(document.documentElement.dir).toBe("rtl");
  });

  it("refuses to switch while a money operation is unresolved", () => {
    // Switching remounts the UI; an unknown transfer outcome must not be dropped.
    render(
      <LangProvider>
        <Probe locked />
      </LangProvider>,
    );
    act(() => screen.getByRole("button").click());
    expect(screen.getByRole("button").textContent).toBe("en:Overview");
    expect(document.documentElement.dir).not.toBe("rtl");
  });
});
