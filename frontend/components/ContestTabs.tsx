"use client";

import { Children, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

// The ballot's races as tabs: one race on screen at a time, the bar pinned
// under the site header so the other races stay one tap away while reading
// a long one. The open race lives in the URL hash (#city_council), so a race
// can be linked to and the back button moves between races.

export interface ContestTab {
  key: string;
  name: string;
  count: string; // "2 candidates"
  rule: string; // "vote for one"
}

export default function ContestTabs({ tabs, children }: { tabs: ContestTab[]; children: ReactNode }) {
  const panels = Children.toArray(children);
  const [active, setActive] = useState(0);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const bar = useRef<HTMLDivElement>(null);

  // follow the hash: on load, and on back/forward
  useEffect(() => {
    const sync = () => {
      const i = tabs.findIndex((t) => `#${t.key}` === window.location.hash);
      if (i >= 0) setActive(i);
    };
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, [tabs]);

  const open = (i: number, focus = false) => {
    setActive(i);
    if (window.location.hash !== `#${tabs[i].key}`) window.history.pushState(null, "", `#${tabs[i].key}`);
    if (focus) buttons.current[i]?.focus();
  };

  // from the bottom of a race: open the next one and bring its top into view
  const openAndScroll = (i: number) => {
    open(i);
    bar.current?.scrollIntoView({ block: "start" });
  };

  const onKey = (e: KeyboardEvent) => {
    const last = tabs.length - 1;
    const to =
      e.key === "ArrowRight" ? (active === last ? 0 : active + 1)
      : e.key === "ArrowLeft" ? (active === 0 ? last : active - 1)
      : e.key === "Home" ? 0
      : e.key === "End" ? last
      : null;
    if (to === null) return;
    e.preventDefault();
    open(to, true);
  };

  const others = tabs.map((t, i) => ({ t, i })).filter(({ i }) => i !== active);

  return (
    <div>
      <div ref={bar} className="sticky top-[65px] z-[5] -mx-4 scroll-mt-[65px] bg-canvas/95 px-4 pb-3 pt-2 backdrop-blur sm:-mx-8 sm:px-8">
        <div className="mb-1.5 flex items-baseline justify-between gap-3">
          <span id="contest-tabs-label" className="text-[11px] font-semibold uppercase tracking-[1px] text-muted">
            Choose a race
          </span>
          <span className="text-[12px] text-muted">
            {tabs.length} races on the ballot · <span className="hidden sm:inline">tap a tab or use ← → keys</span>
            <span className="sm:hidden">tap to switch</span>
          </span>
        </div>
        <div
          role="tablist"
          aria-labelledby="contest-tabs-label"
          onKeyDown={onKey}
          className="grid gap-1 rounded-xl border border-ink/15 bg-card p-1"
          style={{ gridTemplateColumns: `repeat(${tabs.length}, minmax(0, 1fr))` }}
        >
          {tabs.map((t, i) => {
            const selected = i === active;
            return (
              <button
                key={t.key}
                ref={(el) => {
                  buttons.current[i] = el;
                }}
                id={`tab-${t.key}`}
                role="tab"
                type="button"
                aria-selected={selected}
                aria-controls={`panel-${t.key}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => open(i)}
                className={`group rounded-lg px-2 py-2 text-center transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hound sm:px-4 sm:py-2.5 ${
                  selected
                    ? "border border-ink bg-ink text-canvas shadow-sm"
                    : "border border-hairline bg-canvas text-body hover:border-ink hover:text-ink"
                }`}
              >
                <span className="block whitespace-nowrap text-[14px] font-semibold leading-tight sm:text-[17px]">{t.name}</span>
                <span className={`mt-0.5 block text-[11px] leading-tight sm:text-[12px] ${selected ? "text-canvas/70" : "text-muted"}`}>
                  {t.count}
                  <span className="hidden sm:inline"> · {t.rule}</span>
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {panels.map((panel, i) => (
        <div
          key={tabs[i].key}
          id={`panel-${tabs[i].key}`}
          role="tabpanel"
          aria-labelledby={`tab-${tabs[i].key}`}
          tabIndex={0}
          hidden={i !== active}
          className="pt-4 focus-visible:outline-none"
        >
          {panel}
        </div>
      ))}

      <nav aria-label="Other races" className="mt-10 rounded-xl border border-hairline bg-soft px-4 py-4 sm:px-5">
        <div className="mb-2 text-[13px] text-muted">You&apos;re reading {tabs[active].name}. The ballot has more:</div>
        <div className="flex flex-wrap gap-2">
          {others.map(({ t, i }) => (
            <button
              key={t.key}
              type="button"
              onClick={() => openAndScroll(i)}
              className="rounded-full border border-ink bg-canvas px-4 py-2 text-sm font-semibold text-ink hover:bg-ink hover:text-canvas"
            >
              {t.name} <span className="font-normal opacity-70">· {t.count}</span> →
            </button>
          ))}
        </div>
      </nav>
    </div>
  );
}
