// Country name (ESPN's flag alt text) → ISO 3166-1 alpha-2, so we can show a flag emoji
// instead of the country name. Covers every nation that turns up in the draws; anything
// unmapped returns "" so the caller can fall back to the text.
//
// Shared by the draw cards and the matchup panel, which name the same countries and would
// otherwise disagree about which ones they know.
const ISO2 = {
  Andorra: "AD", Argentina: "AR", Armenia: "AM", Australia: "AU", Austria: "AT",
  Belarus: "BY", Belgium: "BE", Bolivia: "BO", "Bosnia and Herzegovina": "BA", Brazil: "BR",
  Bulgaria: "BG", Canada: "CA", Chile: "CL", China: "CN", "Chinese Taipei": "TW",
  Colombia: "CO", Croatia: "HR", Czechia: "CZ", "Czech Republic": "CZ", Denmark: "DK",
  Egypt: "EG", Estonia: "EE", Finland: "FI", France: "FR", Georgia: "GE", Germany: "DE",
  "Great Britain": "GB", "United Kingdom": "GB", Greece: "GR", "Hong Kong": "HK",
  Hungary: "HU", India: "IN", Indonesia: "ID", Israel: "IL", Italy: "IT", Japan: "JP",
  Kazakhstan: "KZ", Korea: "KR", "South Korea": "KR", Laos: "LA", Latvia: "LV",
  Liechtenstein: "LI", Lithuania: "LT", Luxembourg: "LU", Macedonia: "MK",
  "North Macedonia": "MK", Mexico: "MX", Monaco: "MC", Montenegro: "ME", Netherlands: "NL",
  "New Zealand": "NZ", Norway: "NO", Paraguay: "PY", Peru: "PE", Philippines: "PH",
  Poland: "PL", Portugal: "PT", Romania: "RO", Russia: "RU", Serbia: "RS", Slovakia: "SK",
  Slovenia: "SI", "South Africa": "ZA", Spain: "ES", Sweden: "SE", Switzerland: "CH",
  Thailand: "TH", Tunisia: "TN", "Türkiye": "TR", Turkey: "TR", USA: "US",
  "United States": "US", Ukraine: "UA", Uzbekistan: "UZ",
};

// A country name → its 🇫🇷 flag emoji (a pair of regional-indicator letters), or "" when
// the name isn't mapped so the caller can fall back to the text.
export function flagEmoji(country) {
  const cc = ISO2[country];
  return cc ? String.fromCodePoint(...[...cc].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65)) : "";
}
