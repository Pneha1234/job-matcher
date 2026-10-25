import type { Metadata } from "next";

import { Providers } from "@/components/providers";
import { Sidebar } from "@/components/sidebar";
import { themeInitScript } from "@/components/theme-toggle";
import "./globals.css";

export const metadata: Metadata = {
  title: "Job Matcher",
  description: "Personal, local-first job matcher",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // data-theme is set before hydration by themeInitScript.
    <html lang="en" suppressHydrationWarning className="h-full antialiased">
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-full">
        <Providers>
          <div className="grid min-h-screen grid-cols-1 md:grid-cols-[220px_minmax(0,1fr)]">
            <Sidebar />
            <main className="min-w-0 p-4 pb-16 md:px-7 md:pt-5">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
