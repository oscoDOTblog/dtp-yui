import { Geist, Geist_Mono } from "next/font/google";
import { ToastProvider } from "@/components/ui/toast";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
});

export const metadata = {
  title: "CV Job Copilot",
  description: "Local job-search copilot with human approval",
};

const links = [
  { href: "/", label: "Inbox" },
  { href: "/analyze", label: "Analyze" },
  { href: "/gaps", label: "Gaps" },
  { href: "/applications", label: "Applications" },
  { href: "/sources", label: "Sources" },
  { href: "/repositories", label: "Repositories" },
  { href: "/settings", label: "Settings" },
  { href: "/profile", label: "Profile" },
];

export default function RootLayout({ children }) {
  return (
    <html
      lang="en"
      className={`dark ${geistSans.variable} ${geistMono.variable}`}
      suppressHydrationWarning
    >
      <body className="isolate min-h-screen antialiased">
        <ToastProvider>
          <div className="flex min-h-screen flex-col">
            <header className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-4 border-b border-border bg-[rgba(11,11,15,0.85)] px-5 py-4 backdrop-blur-md max-sm:flex-col max-sm:items-start">
              <a
                href="/"
                className="font-heading text-base font-bold tracking-wide text-foreground no-underline hover:no-underline"
              >
                CV <span className="text-primary">Copilot</span>
              </a>
              <nav className="flex flex-wrap gap-x-4 gap-y-2">
                {links.map((link) => (
                  <a
                    key={link.href}
                    href={link.href}
                    className="text-sm text-muted-foreground no-underline transition-colors hover:text-primary hover:no-underline"
                  >
                    {link.label}
                  </a>
                ))}
              </nav>
            </header>
            <main className="mx-auto w-full max-w-[1100px] flex-1 px-5 py-6 pb-12">
              {children}
            </main>
            <footer className="border-t border-border px-5 py-4 text-center text-sm text-muted-foreground">
              Stage 4 · localhost only · evidence-grounded · human approval
              required
            </footer>
          </div>
        </ToastProvider>
      </body>
    </html>
  );
}
