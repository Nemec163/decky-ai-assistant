import { useEffect, useRef } from "react";

/** Delay before re-focusing an element, in ms. Gives Decky/Steam overlays time
 * to settle (e.g. after the virtual keyboard opens) before we grab focus. */
export const FOCUS_DELAY_MS = 80;

/**
 * Returns a `focusWithDelay(fn)` helper plus automatic cleanup: every timer it
 * schedules is tracked and cleared on unmount, so a delayed focus never fires
 * into a torn-down component.
 */
export function useDelayedFocus() {
  const timersRef = useRef<Set<number>>(new Set());

  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      for (const timer of timers) {
        window.clearTimeout(timer);
      }
      timers.clear();
    };
  }, []);

  return (callback: () => void) => {
    const timer = window.setTimeout(() => {
      timersRef.current.delete(timer);
      callback();
    }, FOCUS_DELAY_MS);
    timersRef.current.add(timer);
  };
}
