import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";
import { Toaster } from "@/components/ui/sonner";
import { EventProvider } from "@/components/event-provider";
import { KeyboardProvider } from "@/components/keyboard-provider";
import { AppShell } from "@/components/app-shell";

import "./globals.css";

export const metadata: Metadata = {
  title: "Life Sciences Intelligence",
  description: "Ranked filings and life sciences news intelligence platform"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
          <EventProvider>
            <KeyboardProvider>
              <AppShell>{children}</AppShell>
            </KeyboardProvider>
          </EventProvider>
          <Toaster position="bottom-right" />
        </ThemeProvider>
      </body>
    </html>
  );
}
