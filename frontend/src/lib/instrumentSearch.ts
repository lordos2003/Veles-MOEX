/**
 * Case-insensitive substring search over the instrument list (U2).
 *
 * The matcher covers ticker, name and FIGI — plain substring only, no
 * fuzziness/transliteration: the project must not invent matching rules
 * beyond what the UI task specifies. The search runs over already-loaded
 * ``active=true`` instruments; no per-keystroke broker requests.
 */

export interface SearchableInstrument {
  figi: string;
  ticker?: string | null;
  name?: string | null;
}

export function instrumentMatches(query: string, inst: SearchableInstrument): boolean {
  const q = query.trim().toLowerCase();
  if (q === "") return true;
  return [inst.figi, inst.ticker ?? "", inst.name ?? ""].some((value) =>
    value.toLowerCase().includes(q),
  );
}

export function filterInstruments<T extends SearchableInstrument>(query: string, list: T[]): T[] {
  return list.filter((inst) => instrumentMatches(query, inst));
}
