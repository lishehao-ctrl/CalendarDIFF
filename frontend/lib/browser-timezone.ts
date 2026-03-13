export function getBrowserTimeZone(): string | null {
  try {
    const value = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (typeof value !== "string") {
      return null;
    }
    const trimmed = value.trim();
    return trimmed || null;
  } catch {
    return null;
  }
}
