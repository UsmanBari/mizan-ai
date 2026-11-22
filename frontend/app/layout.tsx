import "./globals.css";
import type { ReactNode } from "react";
import { Public_Sans, Source_Serif_4 } from "next/font/google";
import { Nav } from "@/components/Nav";

const sans = Public_Sans({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const serif = Source_Serif_4({ subsets: ["latin"], variable: "--font-serif", display: "swap" });

export const metadata = { title: "Mizan AI", description: "Ask a PSX company's report a question and see where every number comes from" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable}`}>
      <body>
        <a href="#main" className="skip">Skip to content</a>
        <Nav />
        <main id="main">{children}</main>
        <footer>Research prototype for AI-4009 at FAST-NUCES. Not investment advice: always check the cited page.</footer>
      </body>
    </html>
  );
}
