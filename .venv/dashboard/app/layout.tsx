import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Memphis Tech Events Dashboard",
  description: "Local dashboard over the Memphis events data warehouse and stats API.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
