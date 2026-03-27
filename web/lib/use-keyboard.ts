"use client";

import { useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";

type KeyboardShortcuts = {
  onHelp: () => void;
};

export function useKeyboardNavigation({ onHelp }: KeyboardShortcuts) {
  const router = useRouter();

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      // Ignore if user is typing in an input
      const target = event.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable
      ) {
        return;
      }

      switch (event.key) {
        case "?":
          event.preventDefault();
          onHelp();
          break;
        case "/":
          event.preventDefault();
          // Focus the first search input on the page
          const searchInput = document.querySelector<HTMLInputElement>(
            'input[type="search"], input[name="q"]'
          );
          searchInput?.focus();
          break;
      }

      // "g" prefix shortcuts (go to)
      if (event.key === "g" && !event.metaKey && !event.ctrlKey) {
        const handleSecondKey = (e2: KeyboardEvent) => {
          document.removeEventListener("keydown", handleSecondKey);
          switch (e2.key) {
            case "d":
              e2.preventDefault();
              router.push("/");
              break;
            case "c":
              e2.preventDefault();
              router.push("/companies");
              break;
            case "n":
              e2.preventDefault();
              router.push("/news");
              break;
            case "w":
              e2.preventDefault();
              router.push("/digests");
              break;
          }
        };
        // Listen for the second key for 1 second
        document.addEventListener("keydown", handleSecondKey);
        setTimeout(() => document.removeEventListener("keydown", handleSecondKey), 1000);
      }
    },
    [router, onHelp]
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);
}
