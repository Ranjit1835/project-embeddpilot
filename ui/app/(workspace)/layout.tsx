import type { Metadata } from "next";
import { Saira_Condensed, Spline_Sans_Mono } from "next/font/google";
import "./instrument.css";

/* Typography is scoped to this route so the V1 wizard keeps its Geist pairing.
   Saira Condensed reads as a stamped panel legend; Spline Sans Mono is the
   readout face — narrow, unambiguous digits, no ligatures. */

const panel = Saira_Condensed({
  variable: "--font-panel",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

const readout = Spline_Sans_Mono({
  variable: "--font-readout",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Resource Map — EmbeddPilot",
  description:
    "Live pinout and bus map of the composed system: pin-mux conflicts, bus-address collisions and emulation verdict.",
};

export default function ResourceMapLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className={`${panel.variable} ${readout.variable} ins-root flex-1`}>
      {children}
    </div>
  );
}
