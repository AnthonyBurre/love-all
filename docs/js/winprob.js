// Match win-probability score tree — JS port of
// src/match_charting_project/winprob_match.py (kept in parity by tests).
// Given two players' career serve+return rates, compute a pre-match win probability.

const _gameMemo = new Map();

export function gameWP(g, a, b) {
  if (a >= 4 && a - b >= 2) return 1.0;
  if (b >= 4 && b - a >= 2) return 0.0;
  if (a >= 3 && b >= 3) {
    const d = (g * g) / (g * g + (1 - g) * (1 - g));
    if (a === b) return d;
    return a > b ? g + (1 - g) * d : g * d;
  }
  const key = `${g}:${a}:${b}`;
  if (_gameMemo.has(key)) return _gameMemo.get(key);
  const v = g * gameWP(g, a + 1, b) + (1 - g) * gameWP(g, a, b + 1);
  _gameMemo.set(key, v);
  return v;
}

// pA = serveA - returnB + (1 - mu), clamped; symmetric for pB.
export function matchupStrength(sa, ra, sb, rb, mu, lo = 0.30, hi = 0.92) {
  const clamp = (x) => Math.min(hi, Math.max(lo, x));
  return [clamp(sa - rb + (1 - mu)), clamp(sb - ra + (1 - mu))];
}

export class MatchWP {
  constructor(p1, p2, bestOf = 3, finalTbGames = 6, finalTbTarget = 7) {
    this.p1 = p1; this.p2 = p2;
    this.setsToWin = Math.floor(bestOf / 2) + 1;
    this.finalTbGames = finalTbGames; this.finalTbTarget = finalTbTarget;
    this.hold1 = gameWP(p1, 0, 0); this.hold2 = gameWP(p2, 0, 0);
    this._tb = new Map(); this._set = new Map(); this._match = new Map();
  }

  _tbServerIsStarter(n) { return Math.floor((n + 1) / 2) % 2 === 0; }

  tbWin(a, b, starter1, target = 7) {
    if (a >= target && a - b >= 2) return 1.0;
    if (b >= target && b - a >= 2) return 0.0;
    if (a === b && a >= target - 1) {
      const al = this.p1, be = 1 - this.p2;
      return (al * be) / (al * be + (1 - al) * (1 - be));
    }
    const key = `${a}:${b}:${starter1}:${target}`;
    if (this._tb.has(key)) return this._tb.get(key);
    const server1 = starter1 === this._tbServerIsStarter(a + b);
    const pa = server1 ? this.p1 : (1 - this.p2);
    const v = pa * this.tbWin(a + 1, b, starter1, target) + (1 - pa) * this.tbWin(a, b + 1, starter1, target);
    this._tb.set(key, v);
    return v;
  }

  setWin(ga, gb, p1serves, final = false) {
    if (ga >= 6 && ga - gb >= 2) return 1.0;
    if (gb >= 6 && gb - ga >= 2) return 0.0;
    const tbg = final ? this.finalTbGames : 6;
    if (ga >= tbg && gb >= tbg) {
      return this.tbWin(0, 0, p1serves, final ? this.finalTbTarget : 7);
    }
    const key = `${ga}:${gb}:${p1serves}:${final}`;
    if (this._set.has(key)) return this._set.get(key);
    const gw = p1serves ? this.hold1 : (1 - this.hold2);
    const v = gw * this.setWin(ga + 1, gb, !p1serves, final) + (1 - gw) * this.setWin(ga, gb + 1, !p1serves, final);
    this._set.set(key, v);
    return v;
  }

  matchWin(sa, sb, p1first) {
    if (sa >= this.setsToWin) return 1.0;
    if (sb >= this.setsToWin) return 0.0;
    const key = `${sa}:${sb}:${p1first}`;
    if (this._match.has(key)) return this._match.get(key);
    const final = (sa === this.setsToWin - 1 && sb === this.setsToWin - 1);
    const ps = this.setWin(0, 0, p1first, final);
    const v = ps * this.matchWin(sa + 1, sb, !p1first) + (1 - ps) * this.matchWin(sa, sb + 1, !p1first);
    this._match.set(key, v);
    return v;
  }

  preMatch() { return 0.5 * (this.matchWin(0, 0, true) + this.matchWin(0, 0, false)); }
}

// a, b = {serve, ret} career rates; returns P(player a wins the match).
export function preMatchWP(a, b, mu, bestOf = 3) {
  const [p1, p2] = matchupStrength(a.serve, a.ret, b.serve, b.ret, mu);
  return new MatchWP(p1, p2, bestOf).preMatch();
}
