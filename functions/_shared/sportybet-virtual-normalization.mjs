/**
 * Small, pure parsers used by the SportyBet virtual/eFootball proxy.
 * Keep these independent of network handlers so feed-shape regressions are testable.
 */
export function participantFromName(value) {
  const text = String(value ?? "").trim();
  const match = text.match(/\(([^()]+)\)\s*$/);
  return match?.[1]?.trim() || "";
}

export function marketLineFromSportyBet(market) {
  const direct = market?.line;
  if (direct !== null && direct !== undefined && String(direct).trim() !== "") {
    const value = Number(direct);
    if (Number.isFinite(value)) return value;
  }

  // SportyBet commonly encodes O/U lines in specifiers such as "total=7.5".
  // A single escape before the decimal point is required in a RegExp literal.
  const specifier = String(market?.specifier ?? "");
  const match = specifier.match(/(?:total|line)=([0-9]+(?:\.[0-9]+)?)/i);
  if (!match) return null;

  const value = Number(match[1]);
  return Number.isFinite(value) ? value : null;
}
