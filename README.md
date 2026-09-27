# Lawn Growth

A Home Assistant integration that tells you **when to mow and how high**, per mowing area, from growing conditions instead of a fixed schedule.

It models grass growth each day from your weather forecast (and soil moisture if you have sensors), adds it up since the last cut, and calls a mow due when about a third of the blade has grown back. The recommended cut height follows the season inside the range for your grass type.

It is **advisory**: it never drives a mower. It publishes entities you can show on a dashboard or use in automations (for example, have your mower automation skip an area while **Mowing allowed** is off).

## Install

1. In HACS, add this repository as a custom repository (category **Integration**).
2. Download **Lawn Growth**. While it is in beta, turn on the integration's **Pre-release** switch in HACS first (see [Beta versions](#beta-versions)).
3. Restart Home Assistant.
4. **Settings → Devices & services → Add integration → Lawn Growth.**

## Beta versions

Betas (`X.Y.Z-beta.N`) are published as GitHub pre-releases. HACS offers them only when the repository's **Pre-release** switch is on. Since HACS 2.0 that switch is an entity on the Lawn Growth repository's device under the HACS integration, and it is disabled by default: enable the entity, then turn it on. With it off, HACS offers stable releases only.

## Setup

- **Weather** (required): any weather entity with a daily (or hourly) forecast. Pre-selected with `weather.home` or `weather.forecast_home` if you have one, or your only weather entity.
- **Mowing-season switch** (optional): when it is off, the lawn is out of season.
- **Notify** (optional): where pushes go.
- **Daily run time** (default 05:00): when the day's growth is added.

Then add a **mowing area** — a stretch of lawn you mow together, for example "Front & Side" and "Back". Most lawns need one to start; add more later from the integration's **Configure → Add a mowing area**. Each mowing area becomes its own device with its own advice; assigning that device to a Home Assistant area afterwards is optional and doesn't affect the advice. Pick a **grass type**; it sets the growth curve and default heights, all editable:

| Grass type | Season | Cut range | Overseed target |
|---|---|---|---|
| Tall fescue / blend | cool | 3.0–4.0″ | 2.5″ |
| Kentucky bluegrass | cool | 2.5–3.5″ | 2.0″ |
| Perennial ryegrass | cool | 2.0–3.0″ | 2.0″ |
| Fine fescue | cool | 2.5–4.0″ | 2.0″ |
| Bermuda / Zoysia | warm | 1.0–2.0″ | — |
| St. Augustine | warm | 2.5–4.0″ | — |

Optional per area: **soil moisture sensors** (averaged; GeoDrops sensors are quality-checked automatically) and a **mow counter** — for mowers without an integration, an entity that changes after each mow, such as a counter that goes up by one. Leave it empty if you'll set up a robot mower below.

Add more areas, edit them, or set up a mower from the integration's **Configure** menu.

## Robot mowers

Under **Configure → Mower settings**, pick the mower's activity entity (and which states mean it is mowing — include paused states so a pause doesn't split a run), its blade-height sensor and its location sensor. If you have exactly one lawn-mower entity, these are suggested for you from it and from sensors on the same device; review and save, or change anything first. Then, under **Configure → Edit a mowing area**, pick which of the location sensor's names (for example "Backyard" or "Front Yard" — on a Mammotion/Luba it's the work-area sensor) belong to each mowing area; names you don't assign to any area, like "path" or "Not working", are ignored. Lawn Growth then records each run itself: every area the mower spent at least 10 minutes (configurable) in gets a mow at the blade height it actually used (time-weighted if the height changed mid-run). This works whether the run was started from Home Assistant or the mower's own app.

## Entities (per mowing area)

| Entity | What it tells you |
|---|---|
| Days until mow due | `0`…`10`, or `>10` |
| Growth budget used | % of a third of the last cut height |
| Recommended cut height | the season's target; attribute `next_pass_in` is the height for the next mow |
| Last cut height | the height recorded with the most recent mow |
| Mode | normal, heat hold, dormant, out of season, establishing, first mow ready, overseed prep |
| Mow due / Mowing allowed | binary sensors for automations |
| Growth today, Accumulated growth, Growth potential, Overseed status | details — Overseed status reads "establishing" then "first mow ready" while a seeding grows in |
| Seeding date | set it to log or correct a seeding; empty when none is in progress |
| Last mow | set it to log or correct a mow date; a date older than the one already stored is kept as history only — it won't reset the growth budget or move the stored last-mow date — so the entity keeps showing the newer date |
| Last fertilizer, Last PGR | set either to log or correct an application date; goes back to empty once the record ages past 35 days |
| Soil moisture used, Seedling height estimate | diagnostics |

Buttons per area: **Log mow**, **Log seeding**, **Seedlings ready**, **Log fertilizer**, **Log PGR**. Lawn-wide: **Evaluate now**.

## Services

All take a `device_id` field (one or more mowing-area devices) and accept an optional `date` (today or earlier) where it makes sense:
`lawn_growth.log_mow` (optional `height_in`), `lawn_growth.correct_last_mow`, `lawn_growth.log_seeding`, `lawn_growth.seedlings_ready`, `lawn_growth.log_event` (`kind`: `fert` or `pgr`), `lawn_growth.prep_overseed` (`seed_date`, optional `target_in`, `buffer_days`), `lawn_growth.cancel_overseed`, and `lawn_growth.evaluate_now`.

## How it works

- Daily growth = maximum rate × temperature factor × moisture factor × fertilizer/PGR factor. The temperature factor peaks at 68 °F for cool-season grass and 88 °F for warm-season grass.
- A mow is due when accumulated growth reaches a third of the last cut height.
- Heat hold: 95 °F+ always; 88 °F+ when the soil is also dry (warm-season grass: +10 °F).
- Dormancy: 10 days in a row of very low growth.
- Overseeding: steps the height down so the last safe pass lands a week before the seed date. After seeding, mowing is held (Mowing allowed off) until the estimated seedling height reaches 1.5× the first-mow height, at least 21 days after seeding, or until you press **Seedlings ready**.
