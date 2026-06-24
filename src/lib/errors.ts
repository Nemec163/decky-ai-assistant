/** Normalize any thrown value into a non-empty human-readable message string. */
export function toMessage(error: unknown, fallback = "Something went wrong."): string {
  if (error instanceof Error) {
    return error.message.trim() || fallback;
  }

  if (typeof error === "string") {
    return error.trim() || fallback;
  }

  if (error && typeof error === "object") {
    const payload = error as Record<string, unknown>;
    for (const key of ["message", "error", "detail", "reason"]) {
      const value = payload[key];
      if (typeof value === "string" && value.trim()) {
        return value.trim();
      }
    }

    try {
      const serialized = JSON.stringify(error);
      if (serialized && serialized !== "{}") {
        return serialized;
      }
    } catch {
      // Fall through to the generic string conversion below.
    }
  }

  const text = String(error ?? "").trim();
  return text && text !== "undefined" && text !== "null" && text !== "[object Object]"
    ? text
    : fallback;
}
