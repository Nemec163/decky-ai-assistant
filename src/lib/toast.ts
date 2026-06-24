import { toaster } from "@decky/api";
import { toMessage } from "./errors";

const DEFAULT_TITLE = "Decky AI Assistant";

export function showToast({
  body,
  critical = false,
  fallback = "Done.",
  title = DEFAULT_TITLE,
}: {
  body: unknown;
  critical?: boolean;
  fallback?: string;
  title?: string;
}) {
  toaster.toast({
    title: toMessage(title, DEFAULT_TITLE),
    body: toMessage(body, fallback),
    critical,
  });
}

/** Show a critical toast for any thrown value. */
export function showError(error: unknown, fallback = "Something went wrong.") {
  showToast({
    body: toMessage(error, fallback),
    critical: true,
    fallback,
  });
}
