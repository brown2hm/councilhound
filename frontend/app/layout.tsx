import type { Metadata } from "next";
import { Inter, Newsreader } from "next/font/google";
import Image from "next/image";
import Link from "next/link";
import { Suspense } from "react";
import "katex/dist/katex.min.css";
import "./globals.css";
import NavLinks from "@/components/NavLinks";
import JurisdictionProvider from "@/components/JurisdictionProvider";
import RecordFreshness from "@/components/RecordFreshness";
import { PUBLIC_API_URL } from "@/lib/api";
import { getJurisdiction } from "@/lib/jurisdiction";

const inter = Inter({ subsets: ["latin"], weight: ["400", "500", "600", "700"] });
// the briefing's display face: headlines and section heads read as a paper, not a dashboard
const newsreader = Newsreader({
  subsets: ["latin"],
  weight: ["400", "500"],
  style: ["normal", "italic"],
  variable: "--font-display",
  adjustFontFallback: false,
});

export async function generateMetadata(): Promise<Metadata> {
  const j = await getJurisdiction();
  return {
    metadataBase: new URL(j.site.site_base_url),
    title: {
      default: `CouncilHound — ${j.identity.short_name}`,
      template: "%s — CouncilHound",
    },
    description: `CouncilHound sniffs through ${j.identity.short_name} public meeting records so you can track projects, votes, and decisions over time.`,
    openGraph: {
      siteName: "CouncilHound",
      type: "website",
      images: ["/brand/hound.png"],
    },
    alternates: {
      types: {
        "application/atom+xml": `${PUBLIC_API_URL}/entities/changes.atom`,
        "text/calendar": `${PUBLIC_API_URL}/meetings/upcoming.ics`,
      },
    },
  };
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const j = await getJurisdiction();
  return (
    <html lang="en" className="scroll-smooth">
      <body className={`${inter.className} ${newsreader.variable} flex min-h-screen flex-col bg-canvas text-ink antialiased`}>
        <JurisdictionProvider value={j}>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-xl focus:bg-ink focus:px-4 focus:py-3 focus:text-sm focus:font-semibold focus:text-white"
        >
          Skip to content
        </a>
        <header className="sticky top-0 z-10 border-b border-hairline-soft bg-canvas">
          <div className="relative mx-auto flex h-16 max-w-[1280px] items-center justify-between gap-4 px-4 sm:px-8">
            <Link href="/" className="flex shrink-0 items-center gap-2.5">
              <Image src="/brand/hound.png" alt="" width={41} height={36} className="h-9 w-auto" priority />
              <span className="text-lg font-semibold tracking-[-0.4px]">CouncilHound</span>
            </Link>
            <NavLinks />
          </div>
        </header>
        <main id="main" className="w-full flex-1">
          {children}
        </main>
        <footer className="bg-soft px-4 py-7 sm:px-8">
          <div className="mx-auto flex max-w-[1280px] items-end justify-between gap-5">
            <Image
              src="/brand/hunting.png"
              alt=""
              width={816}
              height={306}
              className="hidden h-auto w-[150px] shrink-0 self-end sm:block"
            />
            <div className="max-w-[520px] space-y-2 text-center">
              <p className="text-[13px] text-body">
                CouncilHound fetches from public {j.identity.short_name}, {j.identity.state_abbr} meeting records on Granicus.
                Summaries are machine-generated — always verify against the linked source documents.
              </p>
              <Suspense fallback={null}>
                <RecordFreshness />
              </Suspense>
              <p className="text-[12px] text-muted">
                <Link href="/glossary" className="font-semibold underline underline-offset-2 hover:text-ink">
                  Glossary
                </Link>
                {" · "}
                <a
                  href={`${PUBLIC_API_URL}/entities/changes.atom`}
                  className="font-semibold underline underline-offset-2 hover:text-ink"
                >
                  Atom feed of changes
                </a>
                {" · "}
                <a
                  href={`${PUBLIC_API_URL}/meetings/upcoming.ics`}
                  className="font-semibold underline underline-offset-2 hover:text-ink"
                >
                  Meeting calendar
                </a>
              </p>
            </div>
            <Image
              src="/brand/fox.png"
              alt=""
              width={610}
              height={409}
              className="hidden h-auto w-[48px] shrink-0 self-end sm:block"
            />
          </div>
        </footer>
        </JurisdictionProvider>
      </body>
    </html>
  );
}
