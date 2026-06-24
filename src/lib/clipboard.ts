import { readBackendClipboard } from "../api/callables";

/**
 * Copy text to the system clipboard. On the Deck this writes through the
 * gamescope Xwayland selection (`execCommand("copy")` is the path that works in
 * Gaming Mode), which other apps and the backend paste reader can then read.
 */
export async function copyTextToClipboard(value: string) {
  const input = document.createElement("input");
  input.value = value;
  input.setAttribute("readonly", "true");
  input.style.left = "-9999px";
  input.style.opacity = "0";
  input.style.position = "fixed";
  document.body.appendChild(input);
  try {
    input.focus();
    input.select();
    input.setSelectionRange(0, value.length);
    if (!document.execCommand("copy")) {
      throw new Error("clipboard copy is unavailable");
    }
  } finally {
    document.body.removeChild(input);
  }
}

/**
 * Read the system clipboard. The backend reads the gamescope Xwayland selection
 * directly via libX11 — the focus-independent path that works in Steam Gaming
 * Mode. Returns "" when the clipboard is empty.
 */
export async function readTextFromClipboard(): Promise<string> {
  const backendClipboard = await readBackendClipboard();
  const text = typeof backendClipboard?.text === "string" ? backendClipboard.text : "";
  if (text.length > 0) {
    return text;
  }
  if (typeof backendClipboard?.error === "string" && backendClipboard.error) {
    throw new Error(backendClipboard.error);
  }
  return "";
}
