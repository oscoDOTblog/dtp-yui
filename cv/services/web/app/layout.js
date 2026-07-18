import "./globals.css";
import styles from "./layout.module.css";

export const metadata = {
  title: "CV Job Copilot",
  description: "Local job-search copilot with human approval",
};

const links = [
  { href: "/", label: "Inbox" },
  { href: "/analyze", label: "Analyze" },
  { href: "/gaps", label: "Gaps" },
  { href: "/profile", label: "Profile" },
  { href: "/applications", label: "Applications" },
];

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <div className={styles.shell}>
          <header className={styles.header}>
            <a className={styles.brand} href="/">
              CV <span>Copilot</span>
            </a>
            <nav className={styles.nav}>
              {links.map((link) => (
                <a key={link.href} href={link.href}>
                  {link.label}
                </a>
              ))}
            </nav>
          </header>
          <main className={styles.main}>{children}</main>
          <footer className={styles.footer}>
            Stage 1 · localhost only · evidence-grounded · human approval required
          </footer>
        </div>
      </body>
    </html>
  );
}
