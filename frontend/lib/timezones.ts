const FALLBACK_TIME_ZONES = [
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "America/Phoenix",
  "America/Anchorage",
  "Pacific/Honolulu",
  "Europe/London",
  "Europe/Paris",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Asia/Singapore",
  "Australia/Sydney",
] as const;

const TIME_ZONE_ALIASES: Record<string, string[]> = {
  la: ["America/Los_Angeles"],
  pacific: ["America/Los_Angeles", "Pacific/Honolulu"],
  pst: ["America/Los_Angeles"],
  pdt: ["America/Los_Angeles"],
  mt: ["America/Denver", "America/Phoenix"],
  mst: ["America/Denver", "America/Phoenix"],
  cst: ["America/Chicago"],
  ct: ["America/Chicago"],
  est: ["America/New_York"],
  et: ["America/New_York"],
  nyc: ["America/New_York"],
  ny: ["America/New_York"],
  london: ["Europe/London"],
  paris: ["Europe/Paris"],
  tokyo: ["Asia/Tokyo"],
  shanghai: ["Asia/Shanghai"],
  singapore: ["Asia/Singapore"],
  sydney: ["Australia/Sydney"],
  hawaii: ["Pacific/Honolulu"],
};

export function listSupportedTimeZones() {
  if (typeof Intl !== "undefined" && "supportedValuesOf" in Intl) {
    try {
      const values = Intl.supportedValuesOf("timeZone");
      if (Array.isArray(values) && values.length > 0) {
        return values;
      }
    } catch {
      // Fall through to fallback list.
    }
  }

  return [...FALLBACK_TIME_ZONES];
}

export function listCommonTimeZones(deviceTimeZone?: string | null) {
  const ordered = [
    deviceTimeZone || null,
    "America/Los_Angeles",
    "America/Denver",
    "America/Chicago",
    "America/New_York",
    "Europe/London",
    "Europe/Paris",
    "Asia/Tokyo",
  ].filter((value): value is string => Boolean(value));

  return Array.from(new Set(ordered));
}

export function formatTimeZoneLabel(timeZone: string) {
  const [region, ...rest] = timeZone.split("/");
  const city = rest.join(" / ").replaceAll("_", " ");
  return {
    title: city || timeZone.replaceAll("_", " "),
    subtitle: region || timeZone,
  };
}

export function searchTimeZones(timeZones: string[], query: string) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return timeZones;
  }

  const aliasMatches = new Set(TIME_ZONE_ALIASES[normalized] || []);
  const shortQuery = normalized.length <= 2;

  return [...timeZones]
    .map((timeZone) => ({ timeZone, score: scoreTimeZoneMatch(timeZone, normalized, aliasMatches, shortQuery) }))
    .filter((row): row is { timeZone: string; score: number } => row.score !== null)
    .sort((left, right) => {
      if (left.score !== right.score) return left.score - right.score;
      const leftLabel = formatTimeZoneLabel(left.timeZone).title;
      const rightLabel = formatTimeZoneLabel(right.timeZone).title;
      if (leftLabel.length !== rightLabel.length) return leftLabel.length - rightLabel.length;
      return left.timeZone.localeCompare(right.timeZone);
    })
    .map((row) => row.timeZone);
}

function scoreTimeZoneMatch(
  timeZone: string,
  normalizedQuery: string,
  aliasMatches: Set<string>,
  shortQuery: boolean,
) {
  if (aliasMatches.has(timeZone)) {
    return 0;
  }

  const lower = timeZone.toLowerCase();
  const { title } = formatTimeZoneLabel(timeZone);
  const lowerTitle = title.toLowerCase();
  const titleTokens = tokenizeTimeZoneText(title);
  const zoneSegments = tokenizeTimeZoneText(timeZone);

  if (lowerTitle === normalizedQuery) return 1;
  if (titleTokens.includes(normalizedQuery)) return 2;
  if (titleTokens.some((token) => token.startsWith(normalizedQuery))) return 3;
  if (zoneSegments.some((segment) => segment.startsWith(normalizedQuery))) return 4;

  if (shortQuery) {
    return null;
  }

  if (lowerTitle.includes(normalizedQuery)) return 5;
  if (lower.includes(normalizedQuery)) return 6;
  return null;
}

function tokenizeTimeZoneText(value: string) {
  return value
    .toLowerCase()
    .replaceAll("/", " ")
    .replaceAll("_", " ")
    .split(/\s+/)
    .filter(Boolean);
}
