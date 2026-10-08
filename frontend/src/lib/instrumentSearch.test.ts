/**
 * U2: live instrument search — case-insensitive substring over ticker / name /
 * FIGI, no fuzziness/transliteration, over already-loaded instruments.
 */
import { describe, expect, it } from "vitest";

import { filterInstruments, instrumentMatches } from "./instrumentSearch";

const INSTRUMENTS = [
  { figi: "BBG004730N88", ticker: "SBER", name: "Сбербанк" },
  { figi: "BBG004730R19", ticker: "GAZP", name: "Газпром" },
  { figi: "BBG012345678", ticker: "ABIO", name: "Артген биотех" },
];

describe("instrumentSearch (U2)", () => {
  it("совпадает по вхождению в середине тикера, без учёта регистра", () => {
    expect(filterInstruments("ab", INSTRUMENTS).map((i) => i.ticker)).toEqual(["ABIO"]);
    expect(filterInstruments("SBER", INSTRUMENTS).map((i) => i.ticker)).toEqual(["SBER"]);
  });

  it("совпадает по названию (кириллица)", () => {
    expect(filterInstruments("газ", INSTRUMENTS).map((i) => i.ticker)).toEqual(["GAZP"]);
    expect(instrumentMatches("артген", INSTRUMENTS[2])).toBe(true);
  });

  it("совпадает по FIGI", () => {
    expect(filterInstruments("004730", INSTRUMENTS).map((i) => i.ticker)).toEqual([
      "SBER",
      "GAZP",
    ]);
    expect(filterInstruments("012345678", INSTRUMENTS).map((i) => i.ticker)).toEqual(["ABIO"]);
  });

  it("пустой/пробельный запрос возвращает весь список", () => {
    expect(filterInstruments("", INSTRUMENTS)).toHaveLength(3);
    expect(filterInstruments("   ", INSTRUMENTS)).toHaveLength(3);
  });

  it("ничего не найдено", () => {
    expect(filterInstruments("ZAZAZA", INSTRUMENTS)).toHaveLength(0);
    expect(instrumentMatches("ZAZAZA", INSTRUMENTS[0])).toBe(false);
  });

  it("не матчит по типу/валюте (только тикер, название, FIGI)", () => {
    expect(filterInstruments("RUB", INSTRUMENTS)).toHaveLength(0);
    expect(filterInstruments("SHARE", INSTRUMENTS)).toHaveLength(0);
  });
});
