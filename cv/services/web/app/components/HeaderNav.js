"use client";

import { ChevronDownIcon } from "lucide-react";
import {
  Menu,
  MenuLinkItem,
  MenuPopup,
  MenuTrigger,
} from "@/components/ui/menu";

const linkClass =
  "text-sm text-muted-foreground no-underline transition-colors hover:text-primary hover:no-underline";

function NavMenu({ label, items }) {
  return (
    <Menu>
      <MenuTrigger
        className={`inline-flex items-center gap-1 bg-transparent p-0 ${linkClass}`}
      >
        {label}
        <ChevronDownIcon aria-hidden className="size-3.5" />
      </MenuTrigger>
      <MenuPopup align="end" sideOffset={8}>
        {items.map((item) => (
          <MenuLinkItem key={item.href} href={item.href}>
            {item.label}
          </MenuLinkItem>
        ))}
      </MenuPopup>
    </Menu>
  );
}

export default function HeaderNav() {
  return (
    <div className="flex flex-1 flex-wrap items-center justify-end gap-x-4 gap-y-2 max-sm:justify-start">
      <nav className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <NavMenu
          label="Inbox"
          items={[
            { href: "/", label: "Inbox" },
            { href: "/analyze", label: "Analyze" },
            { href: "/applications", label: "Applications" },
          ]}
        />
        <NavMenu
          label="Profile"
          items={[
            { href: "/profile", label: "Profile" },
            { href: "/gaps", label: "Gaps" },
            { href: "/repositories", label: "Repositories" },
          ]}
        />
      </nav>
      <NavMenu
        label="Settings"
        items={[
          { href: "/settings", label: "Settings" },
          { href: "/sources", label: "Sources" },
        ]}
      />
    </div>
  );
}
