import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "cmdcode",
  description: "Terminal-first competitive programming",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
