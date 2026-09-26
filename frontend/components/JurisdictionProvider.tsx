"use client";

import { createContext, useContext } from "react";
import { setJurisdiction, type Jurisdiction } from "@/lib/jurisdiction";

const Ctx = createContext<Jurisdiction | null>(null);

/** Hands the server-fetched jurisdiction to client components. Also fills
 * the module memo so the sync helpers in lib/jurisdiction work on the
 * client (this runs before any child renders). */
export default function JurisdictionProvider({ value, children }: { value: Jurisdiction; children: React.ReactNode }) {
  setJurisdiction(value);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useJurisdiction(): Jurisdiction {
  const j = useContext(Ctx);
  if (!j) throw new Error("useJurisdiction() outside <JurisdictionProvider>");
  return j;
}
