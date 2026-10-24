# Lawn Growth

A Home Assistant integration that tells you **when to mow and how high**, per mowing area, from growing conditions instead of a fixed schedule.

It models grass growth each day from your weather forecast (and soil moisture if you have sensors), adds it up since the last cut, and calls a mow due when about a third of the blade has grown back. The recommended cut height follows the season inside the range for your grass type.

It is **advisory**: it never drives a mower. It publishes entities you can show on a dashboard or use in automations (for example, have your mower automation skip an area while **Mowing allowed** is off).

## Requirements

- **Internet access, for the weather forecast.** Lawn Growth makes no network calls itself, but every run needs a forecast from the weather entity you pick, and most weather integrations fetch it from the internet. Without one, the day's run is skipped and retried every 15 minutes until a forecast arrives. Copying events to Google Calendar also needs internet; a Local Calendar doesn't.
- Home Assistant 2026.3 or newer.

## Install

1. In HACS, add this repository as a custom repository (category **Integration**).
2. Download **Lawn Growth**. While it is in beta, turn on the integration's **Pre-release** switch in HACS first (see [Beta versions](#beta-versions)).
3. Restart Home Assistant.
4. **Settings → Devices & services → Add integration → Lawn Growth.**

## Beta versions

Betas (`X.Y.Z-beta.N`) are published as GitHub pre-releases. HACS offers them only when the repository's **Pre-release** switch is on. Since HACS 2.0 that switch is an entity on the Lawn Growth repository's device under the HACS integration, and it is disabled by default: enable the entity, then turn it on. With it off, HACS offers stable releases only.

## Setup

- **Weather** (required): any weather entity with a daily (or hourly) forecast. Pre-selected with `weather.home` or `weather.forecast_home` if you have one, or your only weather entity. If it isn't available yet when Home Assistant starts (common with cloud weather integrations), Lawn Growth still loads and runs as soon as the weather entity comes up, retrying every 15 minutes until a forecast arrives.
- **Mowing-season switch** (optional): when it is off, the lawn is out of season.
- **Notify** (optional): where pushes go.
- **Outdoor temperature sensor** (optional): a weather station's air temperature. Growing degree days then use observed highs and lows, back-filled from the sensor's history; without it they use the weather forecast. You can add or change it any time: the season is then recounted from that sensor's history.
- **Daily run time** (default 05:00): when the day's growth is added.
- **Copy events to calendars** (optional): calendars that get a copy of the firm application events, such as a Local Calendar or Google Calendar. See [Copying events to other calendars](#copying-events-to-other-calendars).

Then add a **mowing area** — a stretch of lawn you mow together, for example "Front & Side" and "Back". Most lawns need one to start; add more later from the integration's **Configure → Add a mowing area**. Each mowing area becomes its own device with its own advice; assigning that device to a Home Assistant area afterwards is optional and doesn't affect the advice. Pick a **grass type**; it sets the growth curve and default heights, all editable:

| Grass type | Season | Cut range | Overseed target |
|---|---|---|---|
| Tall fescue / blend | cool | 3.0–4.0″ | 2.5″ |
| Kentucky bluegrass | cool | 2.5–3.5″ | 2.0″ |
| Perennial ryegrass | cool | 2.0–3.0″ | 2.0″ |
| Fine fescue | cool | 2.5–4.0″ | 2.0″ |
| Bermuda / Zoysia | warm | 1.0–2.0″ | — |
| St. Augustine | warm | 2.5–4.0″ | — |

Optional per area: **soil moisture sensors** (averaged; GeoDrops sensors are quality-checked automatically; their soil temperature at the chosen **soil temperature depth** — 1.5″, 2.5″ (default) or 3.5″ — is tracked too) and a **mow counter** — for mowers without an integration, an entity that changes after each mow, such as a counter that goes up by one. Leave it empty if you'll set up a robot mower below.

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
| Mode | normal, heat hold, dormant, out of season, establishing, first mow ready, overseed prep, hold after spraying |
| Mow due / Mowing allowed | binary sensors for automations; Mowing allowed has a `reason` attribute while it's off |
| Good spray day | on when today passes the spray-day check inside an open post-emergent window (see [Post-emergent](#post-emergent)); attributes list the failed checks and the ones the forecast couldn't answer |
| Growth today, Accumulated growth, Growth potential, Overseed status | details — Overseed status reads "establishing", "seedlings look ready", then "first mow ready" while a seeding grows in |
| Seeding date | set it to log or correct a seeding — this one replaces the stored date; empty when none is in progress |
| Last mow | set it to log a mow on that date (each set adds a mow, it doesn't correct one); a date older than the one already stored is kept as history only, so the entity keeps showing the newer date. Setting the date already shown does nothing |
| Last fertilizer, Last PGR | set either to log an application on that date (each set adds one, it doesn't correct one); goes back to empty once the record ages past 35 days. Setting the date already shown does nothing |
| Soil moisture used, Seedling height estimate | diagnostics |
| Soil temperature | mean soil temperature of the last 5 days from the area's GeoDrops probes, counting only readings taken while the probe reports good quality; unknown while fewer than 3 of those days are complete (for example while the probes are out for winter). Attribute `source` is `geodrops` or `gdd` |
| Winterizer, Overseed window | application window status (see [Application calendar](#application-calendar)). Overseed window exists for cool-season areas only |
| Last winterizer | set it to log a winterizer on that date; it counts as fertilizer for the growth model |
| Post-emergent | the area's post-emergent window status: tentative, projected, open, done, skipped or closed. Attributes: which window (`spring_broadleaf`, `fall_broadleaf`, `young_crabgrass`), today's and tomorrow's spray-day verdict, the last application, `dont_mow_until` and the follow-up date |
| Last post-emergent, Post-emergent product | set the date to log a post-emergent on this area with the selected product (default mesotrione). The product also sets the spray-day check's heat limit and seedling rule |

Lawn-wide: **Growing degree days** — base 50 °F, counted from Jan 1, reset each year. **Pre-emergent** (window status), **Last pre-emergent** (date picker; logs for every area), **Pre-emergent product** (the product Last pre-emergent logs) and the **Applications** calendar.

Buttons per area: **Log mow** (one tap for today, at the area's **Log mow height**) and **Seedlings ready**. **Log mow height** defaults to the last cut height; set it before logging a mow at a different height. The **Last mow** date picker uses it too. Lawn-wide: **Evaluate now**. Log seedings, fertilizer and PGR with their date entities.

## Services

All take a `device_id` field (one or more mowing-area devices) and accept an optional `date` (today or earlier) where it makes sense:
`lawn_growth.log_mow` (optional `height_in`), `lawn_growth.correct_last_mow`, `lawn_growth.log_seeding`, `lawn_growth.seedlings_ready`, `lawn_growth.log_event`, `lawn_growth.skip_application`, `lawn_growth.flag_weeds`, `lawn_growth.prep_overseed` (`seed_date`, optional `target_in`, `buffer_days`), `lawn_growth.cancel_overseed`, and `lawn_growth.evaluate_now`.

- `lawn_growth.log_event`: `kind` is `fert`, `pgr`, `winterizer` or `herbicide`. A herbicide needs a `product`: `prodiamine`, `dithiopyr` or `other_pre_emergent` (pre-emergents), `mesotrione`, `triclopyr_ester` or `other_post_emergent`. Leave `device_id` empty to log for every area, as for a lawn-wide pre-emergent.
- `lawn_growth.skip_application`: `kind` is `pre_emergent` (lawn-wide), `winterizer`, `overseed` or `post_emergent` (for the given areas, or every area). Skips this season's window; logging the application later still marks it done. For post-emergent it skips the area's open windows, or else the next one to open.
- `lawn_growth.flag_weeds`: `target` is `broadleaf` or `crabgrass`. Weeds showed up outside a post-emergent window: opens the matching window for those areas today (broadleaf: the spring window through Jun 30, else the fall one). A window that already closed this season can't be reopened.

## Application calendar

Lawn Growth times pre-emergent, post-emergent, winterizer and fall overseeding from the lawn's own conditions, notifies you when each window opens, and keeps them on its **Applications** calendar together with what you've logged. It's advisory: it never applies anything. The one thing that touches the mower is the short Mowing allowed hold after a post-emergent spray.

Each window goes **tentative** (no signal yet; shown on a typical date) → **projected** (the trigger falls inside the forecast) → **open** (notification sent) → **done** when you log it, **skipped** with `lawn_growth.skip_application`, or **missed** when it closes with nothing logged.

| Window | Opens | Closes (missed) | Typical date |
|---|---|---|---|
| Pre-emergent (lawn-wide) | soil 50 °F, or 125 growing degree days without probes | 14 days after crabgrass germination is expected (55 °F / 200 GDD) | Apr 10 |
| Winterizer (per area) | growth has wound down (fall wind-down, at least 10 days since the last mow with none due), 28 days since the last fertilizer, and the grass is still green (not dormant; soil at least 40 °F where probes are in) | the area goes dormant, or soil under 40 °F for 3 days | Nov 5 |
| Fall overseed (per area) | from August, soil below 70 °F (without probes: a 7-day air mean at or below 72 °F and falling); best at 60–70 °F | soil below 55 °F, or a 7-day air mean below 50 °F | Aug 25 |

Soil here is the 5-day Soil temperature. The pre-emergent follows the warmest area's probes, or growing degree days for areas without them, whichever triggers first.

- **Notifications** (to the Notify target, once per window per season): pre-emergent heads-up (47 °F and rising / 75 GDD — time to buy product), apply now, late warning (53 °F / 175 GDD), germination expected (suggests dithiopyr, which still controls very young crabgrass) and missed; winterizer open; overseed open and closing in about a week; and "soil probes back online" when an area switches from growing degree days back to its probes (about 3 days of good readings after they go back in). Areas crossing together share one message. Alerts set from air temperatures say so.
- **Products and seeding.** Logging a pre-emergent makes the window done. Prodiamine blocks seeding for 16 weeks, dithiopyr 12, triclopyr ester 4; mesotrione never blocks. These are placeholder defaults: check the label of the product you use. A Prepare for overseeding seed date inside a block, or a blocking product on an area that's establishing, sends a warning. Seven weeks after the first pre-emergent, a reminder suggests a second (split) application of dithiopyr, and the Pre-emergent product select suggests dithiopyr.
- **The calendar** shows the windows (projections move with the forecast), a "Start overseed prep" milestone, a planned overseed seed date in place of its window, post-emergent follow-ups, and logged seedings, fertilizer, PGR, winterizer and herbicides ("Prodiamine — whole lawn") for 400 days. Same-day events across areas merge. Mows aren't shown.

### Post-emergent

Post-emergent goes on as spot or area treatments, so each mowing area has its own windows, and Lawn Growth checks each day inside an open window whether today and tomorrow are good days to spray.

| Window | Opens | Closes | Typical date |
|---|---|---|---|
| Spring broadleaf | soil 55 °F, or 250 growing degree days without probes | forecast highs of 85 °F or more on 3 of the next 5 days, or after Jun 30 | May 10 |
| Fall broadleaf (the most effective: weeds are moving sugars to their roots) | from Aug 15, a 7-day air mean at or below 70 °F | the area goes dormant, or a 7-day air mean below 45 °F | Sep 20 |
| Young crabgrass | 14 days after crabgrass germination is expected, only when the pre-emergent was missed, skipped or went down after germination | 6 weeks later, as crabgrass starts tillering | — |

A window stays **open** after you spray, since weeds often need a follow-up. When it closes it reads **done** if you logged a post-emergent in it, or **closed** if you didn't (no weeds isn't a miss). Use `lawn_growth.flag_weeds` when weeds show up outside a window.

**Spray-day check.** A day is good when all of these pass:

1. **Temperature:** the forecast high is 60–85 °F. Triclopyr ester turns volatile in heat, so its limit is 80 °F, checked against the next day's high too.
2. **Rain-free:** under a 30 % chance of rain for 24 hours from 8 am, from the hourly forecast, else the daily one.
3. **Wind:** under 10 mph from 6 am to noon, from the hourly forecast.
4. **Mowing:** no mow in the last 2 days and none due in the next 2. When a mow is due soon the notice says "mow first, spray 2 days later".
5. **Grass not stressed:** no heat stress, not dormant, soil not dry.
6. **Seedlings:** the product is safe on the area's grass. On new seed, mesotrione waits for Seedlings ready; triclopyr ester and Other wait until the area has been mowed 3 times after it.

Weather integrations differ: hourly forecasts, wind and rain chance are all optional in Home Assistant. A check the forecast can't answer is skipped, and the notice and the `not_checked` attribute name it.

**After you log a post-emergent** (Last post-emergent, or `lawn_growth.log_event` with a post-emergent product):

- A notification says "don't mow until" 2 days later, and **Mowing allowed** turns off for that area until then, so a robot mower stays off. Mode reads "hold after spraying" and Mowing allowed's `reason` says why. While seedlings are establishing, the hold only adds to the establishment hold: Seedlings ready is still the only way to turn mowing back on.
- Triclopyr ester gets a follow-up reminder 21 days later (a notification and a calendar event). Mesotrione has none.
- Its wait before seeding (triclopyr ester 4 weeks) feeds the same seeding check as the pre-emergents. Logging it on an area with new seedlings sends a warning.

**Notifications:** a window opening; "Good spray day tomorrow", at most once every 3 days per area while a window is open and nothing has been sprayed in it; "don't mow until" after a log; and the follow-up reminder.

These defaults (the 80 °F limit, 3 mows, 21 days, 4 weeks, 24 hours rain-free) are placeholders: check the label of the product you use.

### Copying events to other calendars

Lawn Growth's own calendar stays inside Home Assistant. To keep the events next to your other calendars, or on your phone, pick one or more calendars under **Configure → Lawn settings → Copy events to calendars**. It's optional: leave it empty and nothing is written anywhere. How a calendar is kept depends on what its integration can do:

- **Mirrored** (calendars that can delete events, such as [Local Calendar](https://www.home-assistant.io/integrations/local_calendar/) and [Google Calendar](https://www.home-assistant.io/integrations/google/)): the calendar matches Lawn Growth's own, estimates included. On every run, Lawn Growth adds new events, moves estimates whose date changed, and removes events that no longer apply (a skipped window, a corrected seeding date). Events older than a year are left alone, so aged-out logs stay as a record.
- **Firm events only** (calendars that can create events but not delete them): a window opening (including "Post-emergent window open"), the pre-emergent late warning, the second (split) pre-emergent reminder, a post-emergent follow-up, and every logged application (seedings, fertilizer, PGR, winterizer, herbicides), each added once and never changed. Tentative and projected dates, prep milestones, planned seed dates, missed windows and mows stay on Lawn Growth's own calendar.

Either way:

- **Only Lawn Growth's events are touched.** Each one is an all-day event whose description ends with a `Lawn Growth key` line; events without that line (yours, or another automation's) are never changed or removed. Don't edit that line.
- **When you add a calendar**, what's already on Lawn Growth's calendar (up to 400 days of logs) is copied to it, once.
- **Which calendars:** the picker lists calendars whose integration can create events. Local Calendar keeps a separate calendar inside Home Assistant, such as one next to a mowing log. Google Calendar reaches your phone through the Google Calendar app, or Apple Calendar with the Google account added: set up Home Assistant's Google Calendar integration first, with **read/write** access (its docs cover the application credentials). With Google, mirrored estimates move on your phone as the forecast changes.
- **When it can't write** (the calendar is gone, or writing to it has failed for 3 days), a repair appears under Settings → System → Repairs. Lawn Growth keeps trying; the repair clears once it works again, or when you take that calendar out of the setting.
- Reminders still come from the Notify target. The target calendar's own default reminders, if any, also apply.

## How it works

- Daily growth = maximum rate × temperature factor × moisture factor × fertilizer/PGR factor. The temperature factor peaks at 68 °F for cool-season grass and 88 °F for warm-season grass.
- A mow is due when accumulated growth reaches a third of the last cut height.
- Heat hold: 95 °F+ always; 88 °F+ when the soil is also dry (warm-season grass: +10 °F).
- Dormancy: 10 days in a row of very low growth.
- Overseeding: steps the height down so the last safe pass lands a week before the seed date. After seeding, mowing is held (Mowing allowed off) until you press **Seedlings ready**. Once the estimated seedling height reaches 1.5× the first-mow height, at least 21 days after seeding, you get a notification and Overseed status reads "seedlings look ready", but mowing stays held until you press the button. Mows logged before then are kept as establishment mows; the first mow after Seedlings ready ends establishment.
