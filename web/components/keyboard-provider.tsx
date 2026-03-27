"use client";

import { useState } from "react";
import { useKeyboardNavigation } from "@/lib/use-keyboard";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";

const shortcuts = [
  { keys: ["?"], description: "Show this help" },
  { keys: ["/"], description: "Focus search" },
  { keys: ["g", "d"], description: "Go to Dashboard" },
  { keys: ["g", "c"], description: "Go to Companies" },
  { keys: ["g", "n"], description: "Go to News" },
  { keys: ["g", "w"], description: "Go to Digests" },
];

export function KeyboardProvider({ children }: { children: React.ReactNode }) {
  const [helpOpen, setHelpOpen] = useState(false);

  useKeyboardNavigation({ onHelp: () => setHelpOpen(true) });

  return (
    <>
      {children}
      <Dialog open={helpOpen} onOpenChange={setHelpOpen}>
        <DialogContent className="max-w-sm">
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>
            Navigate faster with these shortcuts.
          </DialogDescription>
          <div className="space-y-2 mt-2">
            {shortcuts.map((shortcut) => (
              <div key={shortcut.description} className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{shortcut.description}</span>
                <div className="flex gap-1">
                  {shortcut.keys.map((key) => (
                    <kbd
                      key={key}
                      className="px-2 py-0.5 rounded border border-border bg-muted font-mono text-xs"
                    >
                      {key}
                    </kbd>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
