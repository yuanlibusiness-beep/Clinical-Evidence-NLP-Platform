import type { Metadata } from "next";

import { AuthProvider } from "@/components/AuthProvider";

import "./globals.css";

export const metadata: Metadata = {
  title: "Clinical Evidence NLP Platform",
  description:
    "Turns clinical papers into structured, source-grounded evidence reviews — every field backed by a verbatim quote.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
