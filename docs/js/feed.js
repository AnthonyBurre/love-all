// The draw feed's own vocabulary — the handful of facts about `brackets.json` that more
// than one renderer has to agree on.
//
// The draw and the panel both answer to them — a card and the drawer it opens have to agree
// about which sides are players and what the event is called — so they are defined here once
// and imported, rather than restated in each renderer where the two copies can drift apart.
//
// Nothing here renders anything. The module is the shape of the feed, so the reasons a
// given caller cares live at the call site, not down here.

// "Bye" and "TBD" are the feed's two slot markers: a side that fills a card but has no
// player behind it to look anything up for. `BYE` is the string `live.draws` writes
// (draws.BYE, kept in step with this) for the entrant-less half of a bye slot.
export const BYE = "Bye";

export const isEntrant = (s) => !!s.name && s.name !== "TBD" && s.name !== BYE;

// What to call an event on screen. The feed's own name is the title sponsor's — "National
// Bank Open presented by Rogers" — which is not what anyone calls the thing, so this leads
// with the name the calendar says people use. Keyed identity stays on the feed name: it's
// the stable one, it's what pairs the two draws of an event, and a calendar that can't
// place an event doesn't change it.
export const ename = (t) => (t.event || {}).common_name || t.name;
