"use client";

import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Follow-a-topic signup: email in, confirmation link out. Kept dumb on
 * purpose — all state lives server-side in topic_subscriptions. */
export default function FollowTopic({ entitySlug }: { entitySlug: string }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "already" | "error">("idle");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || state === "sending") return;
    setState("sending");
    try {
      const resp = await fetch(`${API}/subscriptions/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, entity_slug: entitySlug }),
      });
      if (!resp.ok) throw new Error();
      const data = await resp.json();
      if (data.status === "already-following") setState("already");
      else if (data.status === "confirmation-sent") setState("sent");
      else throw new Error(); // email-unavailable and anything unexpected
    } catch {
      setState("error");
    }
  }

  if (state === "sent")
    return <p className="text-sm text-muted">Check your inbox — click the confirmation link to start following.</p>;
  if (state === "already")
    return <p className="text-sm text-muted">You&apos;re already following this topic.</p>;

  if (!open)
    return (
      <button
        onClick={() => setOpen(true)}
        className="rounded-full border border-ink px-4 py-2 text-sm font-semibold text-ink hover:bg-ink hover:text-canvas"
      >
        Follow this topic
      </button>
    );

  return (
    <form onSubmit={submit} className="flex w-full max-w-[420px] items-center gap-2">
      <input
        type="email"
        required
        autoFocus
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@example.com"
        className="min-w-0 flex-1 rounded-xl border border-hairline bg-canvas px-4 py-2.5 text-sm outline-none placeholder:text-muted-soft focus:border-ink"
      />
      <button
        disabled={state === "sending"}
        className="shrink-0 rounded-xl bg-ink px-4 py-2.5 text-sm font-semibold text-white hover:bg-ink-active disabled:opacity-60"
      >
        {state === "sending" ? "…" : "Follow"}
      </button>
      {state === "error" && <span className="text-xs text-tint-coral-text">Try again</span>}
    </form>
  );
}
