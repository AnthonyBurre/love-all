# Reading the site

How to read the patterns, trigger tokens and court diagrams in a matchup panel. For what the
site is and how it is built, see the [main README](../README.md#the-site).

Zones in a pattern are named by the **player's own hands**: "the BH corner" is that
player's backhand corner whether they are left- or right-handed. Run-around shots get their
tennis names, so a forehand played from the backhand corner is `inside-out` on the diagonal
and `inside-in` down the line. Every pattern shown repeated in both halves of the player's
charted matches.

## The trigger tokens

Each stroke is one token:

- **Wing and type.** `FH` / `BH` is the forehand or backhand wing the player actually hit
  with. The type is `drive` (flat or topspin), `slice` (slice or chip), `net` (volley,
  overhead, half-volley, or swinging volley), `drop` or `lob` (the shortest and deepest
  balls in tennis, so each gets its own group), or `shot` when the type was not charted.
- **Direction.** `→1` / `→2` / `→3` is the third of the court the ball was sent to, named
  relative to the **player's own hands**: mirrored for a left-hander, so one token string
  means the same shot whoever played it. The raw notation names fixed thirds by the
  right-hander convention, which would make a lefty's crosscourt forehand and a righty's read
  as different shots and their mirror images read as the same one. `→·` means the direction
  was not charted.
- **Serves.** A serve is written as its target: `serve wide`, `serve body`, or `serve T`.

A trigger reads as a lead-up, the player's shot then the opponent's reply, and asks what that
cue provokes. The framework groups a player's point-ending shots as one behavioral unit, the
**aggressive shot**: a winner, their own unforced error, or a shot that forced the reply into an
error. All three mean they went for the finish and only the execution differed. "Aggressive" is
the **aggressive shot frequency** the cue provokes, and "converts" is the share that paid,
winners and forced errors together. A cue that raises the frequency but sinks conversion is a
**trap**.

That numerator matches the one behind
[Aggression Score](https://www.tennisabstract.com/blog/2015/08/31/measuring-wta-tactics-with-aggression-score/);
[`shot_triggers`](../experiments/shot_triggers/) carries the split-half test that settled it.

## The court diagram

The diagram is a **placement map**, not a flight path. The player's half of the court is
tinted, their own balls are solid lines in their colour, and the opponent's are dashed and
grey. Lines run from one contact to the next, and a ring marks where a ball bounced, so a
line with no ring is a ball taken out of the air (a volley). It comes in two forms:

- **A pattern** draws the incoming ball landing on the near half, the player's side, so
  "into the BH corner" points where you'd expect, and the response, with an arrowhead,
  landing up top. For return patterns the incoming bounce sits short, mid-court, or deep to
  match the charted return depth.
- **A trigger sequence** plays out the lead-up shots, ending on the ball the player
  attacked. The attacking shot itself isn't drawn, because the stored pattern doesn't say
  where it went. Opening cues are drawn on their own service court; pooled triggers have no
  court, so their serves are drawn in the deuce court.

## Zones and how fine the charting really is

The placement is **coarse on purpose**, and the diagram shows only what was charted:

- **Three lateral zones.** Direction is recorded as one of three thirds, not a continuous
  spot, so two shots into different parts of the same third are the same zone. Within a
  third the diagram cannot separate a sharp crosscourt from a safer one.
- **Lines come from zone pairs.** A single zone code never says crosscourt or down the
  line, but a pattern knows both ends: the zone the ball arrived in fixes where the player
  stood, so zone-to-zone geometry names the line. The two ends face each other, which is why
  a reply into the *same-numbered* third travels the diagonal.
- **Depth is thin.** The raw notation carries a coarse depth (shallow / mid / deep) on
  about three-quarters of returns but few later balls, so only the off-the-return patterns
  use it. Trigger drawings put every rally bounce at one mid-court depth.
- **Three serve targets.** Wide, body, or T, placed in the service box the serve crosses
  into.

## Does handedness matter?

The **wing** is always right: `FH` / `BH` is the stroke the player actually made, taken
straight from the notation, so it holds for left-handers and right-handers alike.

For **court patterns**, handedness is already folded in. The zones are flipped for
left-handers before anything is counted or compared, so "drive into the BH corner" means the
same tennis problem for Nadal as for Federer, and the comparison against the tour is like
for like. Without the flip, a lefty answering his forehand corner with a forehand posts a
large, meaningless lift against a mostly right-handed tour.

The **trigger tokens** are flipped the same way, so `→1` is always the player's own
forehand side. The diagram flips them back, so the ball is drawn where it physically went.
