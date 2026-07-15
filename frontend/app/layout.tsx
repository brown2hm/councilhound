import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Image from "next/image";
import Link from "next/link";
import "./globals.css";
import NavLinks from "@/components/NavLinks";

const inter = Inter({ subsets: ["latin"], weight: ["400", "500", "600", "700"] });

export const metadata: Metadata = {
  title: "CouncilHound — City of Fairfax",
  description:
    "CouncilHound sniffs through City of Fairfax council and planning commission records so you can track projects, votes, and decisions over time.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="scroll-smooth">
      <body className={`${inter.className} flex min-h-screen flex-col bg-canvas text-ink antialiased`}>
        <header className="sticky top-0 z-10 border-b border-hairline-soft bg-canvas">
          <div className="mx-auto flex h-16 max-w-[1280px] items-center justify-between px-8">
            <div className="flex items-center gap-10">
              <Link href="/" className="flex items-center gap-2.5">
                <Image src="/brand/hound.png" alt="" width={41} height={36} className="h-9 w-auto" priority />
                <span className="text-lg font-semibold tracking-[-0.4px]">CouncilHound</span>
              </Link>
              <NavLinks />
            </div>
          </div>
        </header>
        <main className="w-full flex-1">{children}</main>
        <footer className="bg-soft px-8 py-7">
          <div className="mx-auto flex max-w-[1280px] items-end justify-between gap-5">
            <Image
              src="/brand/hunting.png"
              alt=""
              width={816}
              height={306}
              className="hidden h-auto w-[150px] shrink-0 self-end sm:block"
            />
            <p className="max-w-[520px] text-center text-[13px] text-body">
              CouncilHound fetches from public City of Fairfax, VA meeting records on Granicus.
              Summaries are machine-generated — always verify against the linked source documents.
            </p>
            <Image
              src="/brand/fox.png"
              alt=""
              width={610}
              height={409}
              className="hidden h-auto w-[48px] shrink-0 self-end sm:block"
            />
          </div>
        </footer>
      </body>
    </html>
  );
}
