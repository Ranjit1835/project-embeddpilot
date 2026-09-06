import type { Metadata } from "next";
import { Archivo, Saira_Condensed, Spline_Sans_Mono } from "next/font/google";
import { SiteFooter } from "@/components/site/SiteFooter";
import { SiteHeader } from "@/components/site/SiteHeader";

/* Typography is scoped to this route group so the workspace keeps its own
   pairing. Archivo is the voice — an industrial grotesque that stays tight and
   confident at display sizes. Spline Sans Mono is the readout face (narrow,
   unambiguous digits, no ligatures) and matches the workspace exactly. Saira
   Condensed is the stamped panel legend. */

const sans = Archivo({
  variable: "--font-site-sans",
  subsets: ["latin"],
  display: "swap",
});

const mono = Spline_Sans_Mono({
  variable: "--font-site-mono",
  subsets: ["latin"],
  display: "swap",
});

const legend = Saira_Condensed({
  variable: "--font-site-legend",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "EmbeddPilot — firmware proven by running it",
    template: "%s — EmbeddPilot",
  },
  description:
    "EmbeddPilot turns a plain-English requirement into embedded firmware, cross-compiles it for ARM and boots it on an emulated STM32F4. Behaviour is demonstrated by a real emulated run, not asserted.",
};

export default function SiteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div
      className={`${sans.variable} ${mono.variable} ${legend.variable} site-root site-bench site-grain flex min-h-full flex-1 flex-col`}
    >
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60] focus:rounded-sm focus:border focus:border-accent-dim focus:bg-panel focus:px-3 focus:py-2 focus:text-[13px] focus:text-accent"
      >
        Skip to content
      </a>
      <SiteHeader />
      <main id="main" className="relative z-10 flex-1">
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
