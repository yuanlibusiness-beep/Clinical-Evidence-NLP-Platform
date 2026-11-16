"use client";

/**
 * Reviewer verification marks.
 *
 * Kept per extraction in this browser's localStorage: verifying is a personal
 * working state ("I have checked this cell against the paper"), and a new
 * extraction run starts unverified because its values may differ. Storage can
 * be unavailable (private mode, blocked site data), in which case marks simply
 * last for the session.
 */

import { useCallback, useEffect, useState } from "react";

const PREFIX = "cenp.verified.";

function read(key: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(key);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

export function useVerification(extractionId: string | null) {
  const [verified, setVerified] = useState<Set<string>>(new Set());

  useEffect(() => {
    setVerified(extractionId ? read(PREFIX + extractionId) : new Set());
  }, [extractionId]);

  const toggle = useCallback(
    (path: string) => {
      if (!extractionId) return;
      setVerified((current) => {
        const next = new Set(current);
        if (next.has(path)) next.delete(path);
        else next.add(path);
        try {
          window.localStorage.setItem(PREFIX + extractionId, JSON.stringify(Array.from(next)));
        } catch {
          /* session-only */
        }
        return next;
      });
    },
    [extractionId],
  );

  return { verified, toggle };
}
