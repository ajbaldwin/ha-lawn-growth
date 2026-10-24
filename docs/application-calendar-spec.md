# Application calendar — spec (draft)

Status: 2026-10-20. P1 (§1), P2 (§2.1–2.3, §2.5, §3–4 without post-emergent), P3 (§5) and P4 (§2.4 and its parts of §3–4) are built. See "P2 as built", "P3 as built", "P4 as built" and "Mirror mode" below for the choices made where the spec left room.

## Goal

Time pre-emergent, post-emergent, winterizer and fall overseeding from the lawn's own conditions instead of calendar guesses, then:

- notify when each application's window opens (the existing Notify target),
- keep a calendar of upcoming windows and logged applications inside Home Assistant,
- optionally write the firm ones (a window opening, a logged application) to a calendar the user picks, such as Google Calendar, so they reach the phone through HA's own calendar services.

Advisory only, like the rest of Lawn Growth: it never applies anything. The one exception touching the mower is the Mowing allowed hold after a post-emergent (§2.4, on by default, D15).

## Decisions so far

| # | Decision | Date |
|---|---|---|
| D1 | Phone delivery: Lawn Growth optionally writes **firm events into any calendar that supports creating events** — Google Calendar being the main case — through the core `calendar.create_event` service (§5). No custom ICS feed: HA has no native one. *(Changed 2026-10-17; first decided as an ICS feed.)* | 2026-10-17 |
| D2 | Inside HA, Lawn Growth gets **its own `calendar` entity**, which also shows tentative and projected dates. | 2026-10-17 |
| D3 | Soil temperature comes from **GeoDrops** when the probes are in the ground and reading good quality; otherwise from **growing degree days (GDD)**. No third-party soil-temperature service. | 2026-10-17 |
| D4 | Probes come out of the ground for winter. The source switches to GDD on its own, and **back to GeoDrops on its own** once the probes are online and their reading quality is established. | 2026-10-17 |
| D5 | v1 covers pre-emergent, **post-emergent**, winterizer, the fall overseed window, and history of logged applications. | 2026-10-17 |
| D6 | Probe usability comes from **GeoDrops' own quality and health sensors**, not from a time-based settling period. | 2026-10-17 |
| D7 | GeoDrops depths: D1 = 1.5″, D2 = 2.5″, D3 = 3.5″. Soil temperature defaults to **D2**. | 2026-10-17 |
| D8 | Pre-emergent **late warning at 175 GDD50**; the other thresholds rescaled around it (§2.1). | 2026-10-17 |
| D9 | `hardware_check` is **ignored** in v1: it doesn't exclude a reading. | 2026-10-17 |
| D10 | Herbicide logging is **product-aware**: prodiamine, dithiopyr, mesotrione, triclopyr ester, other. | 2026-10-17 |
| D11 | Pre-emergent (prodiamine, dithiopyr) is a **blanket, lawn-wide** application: one window for the whole lawn. Mesotrione is a **per-area spot** application, logged without a window. | 2026-10-17 |
| D12 | Typical dates approved: pre-emergent Apr 10, winterizer Nov 5, overseed window Aug 25. | 2026-10-17 |
| D13 | Winterizer rule in §2.2 approved. | 2026-10-17 |
| D14 | The post-emergent product list ships with **mesotrione**, **triclopyr ester** and Other. | 2026-10-17 |
| D15 | **Hold Mowing allowed after a post-emergent** spray: on by default. | 2026-10-17 |
| D16 | The phone-calendar setting takes **several calendars** ("Copy events to calendars"), each with its own ledger — e.g. a Local Calendar next to a mowing log now, Google Calendar for the phone later. | 2026-10-17 |
| D17 | **Mirror mode:** a calendar that can delete events (Local Calendar, Google Calendar) mirrors Lawn Growth's whole calendar, estimates included, kept in step on every run. Create-only calendars keep firm events only (§5). | 2026-10-20 |

## 1. Temperature signals

### 1.1 Soil temperature from GeoDrops (preferred)

The probes are the GeoDrops devices behind the area's soil moisture sensors (no separate setting, as built in P1). Lawn Growth finds each device's sibling entities itself, the same way it already finds the depth-quality sensors for moisture (`inputs.py` `_geodrops_qualities`). Depth setting per area, default **D2 (2.5″)**; D1 = 1.5″, D3 = 3.5″.

**What GeoDrops gives us** (from the GeoDrops integration and ten days of recorder history on a seven-probe install):

| Entity | States | Observed behaviour |
|---|---|---|
| `…_quality_depth_N` (Reading Quality, per depth) | `good`, `poor`, `bad`, `training` | A newly installed probe reads `training` for about 1.5 days, then `good`. A single depth can stay `poor` for weeks while the others are `good`. |
| `…_status` (Probe Health) | `ok`, `calibrating`, `max_moisture_required`, `wick_renewal_needed`, `hardware_check`, `error` | `calibrating` while a new probe trains, sometimes followed by a brief `max_moisture_required`. `hardware_check` can blip for one poll or last a day or more. |
| `…_temperature_depth_N` | °C natively (HA converts) | — |
| entity availability | goes `unavailable` once the last reading is > 12 h old (GeoDrops' skip threshold) | HA restarts show as short `unavailable` gaps |

`calibrating` covers GeoDrops' new-sensor and **temperature-learning** codes (`ATT_SS_NEW`, `MEM_T_LRN`), and per-depth quality reads `training` at the same time. That is GeoDrops' own settling signal after a probe goes in, so no time-based settling rule is needed. A probe that stops reporting goes `unavailable` after 12 h; one still reporting from a shelf fails the moisture quality check.

A **reading is usable** when, at the time it was taken:

- the temperature entity at the chosen depth is available and numeric,
- that depth's Reading Quality is `good` (`poor`, `bad`, `training`, `unknown` and `unavailable` all exclude it),
- Probe Health is `ok`, `max_moisture_required`, `wick_renewal_needed` or `hardware_check`. `calibrating`, `error` and `unknown` exclude it.

`max_moisture_required` and `wick_renewal_needed` are about moisture calibration and the wick, not temperature. `hardware_check` covers both a moisture and a temperature hardware code (`CHK_M_HWR`/`CHK_T_HWR`); v1 ignores it (D9) because the blips observed were short. If it turns out to matter, enabling GeoDrops' raw `next_action_codes` entity would let Lawn Growth exclude only `CHK_T_HWR`.

**Daily soil temperature** for an area: at the daily run, read yesterday's recorder state history for each probe's temperature, quality and health entities. Keep the temperature readings that were usable when taken, and average them across the area's probes. The day counts only if usable readings cover **at least 75 % of the day** — that's a fair-average check, not a settling timer, because a mean of only the afternoon readings would run warm. Otherwise the day has no soil value.

Trigger value **Soil5** = mean of the valid days among the trailing 5, needing **at least 3 valid days**.

### 1.2 Growing degree days (fallback, always computed)

Lawn-wide, base 50 °F, simple-average method:

`GDD_day = max(0, (Tmax + Tmin) / 2 − 50)`, accumulated from **Jan 1** (configurable; MSU's GDDTracker starts Feb 15, which changes almost nothing at base 50 in a northern winter).

Inputs, in order:

1. New optional lawn-wide setting **Outdoor temperature sensor** (e.g. a weather station's air temperature). Yesterday's min/max come from recorder long-term statistics, so a restart or missed run can be back-filled and nothing depends on the integration running at the right moment.
2. Otherwise the weather entity's daily high/low, as the daily run already reads them today (forecast, not observed — less accurate).

GDD is stored in its own accumulator, not in the area history (`history_days` is 45, too short). The previous season's final total is kept for later tuning.

Daily runs already happen out of season (`evaluate.py` accrues every day; only mowing advice changes), so GDD keeps counting through winter. Spec requirement: keep that true, and add a test for it.

### 1.3 Source selection (per area, daily)

```
            Soil5 available (≥ 3 valid days in the last 5)
   GDD  ───────────────────────────────────────────────▶  GEODROPS
        ◀───────────────────────────────────────────────
            Soil5 not available
```

- The rule is the same in both directions, and it follows the quality data alone. A short outage costs at most one day's value and doesn't change the source. Pulling the probes in late fall switches to GDD within about 3 days. Putting them back in spring switches back about 3 days after GeoDrops reports `good`/`ok` again.
- Every window, event and notification records the source that set it.
- Optional notification on a switch: "Soil probes back online in <area> — pre-emergent tracking now uses soil temperature."
- **GeoDrops' Active switch** (GeoDrops 0.9.0-beta.3: a per-probe `switch`, unique ID `<serial>_active`) isn't read. Turned off, it makes every probe sensor except Last Reading `unavailable`, which §1.1 already treats as unusable, so a probe taken out of service drops to GDD by the same 3-day rule, and one turned back on returns once its readings are good again. Reading it could switch to GDD the same day every probe in an area goes inactive, and drop "put the probes in" from the air-temperature note while they're out on purpose; neither is worth a dependency on a recent GeoDrops version.
- A window that already opened stays open after a switch. A switch never sends a second "apply now" for the same window.

## 2. Applications

Each application kind has at most one **window** per season — lawn-wide for pre-emergent (D11), per area for winterizer and overseed — with a status:

`tentative → projected → open → done` (or `skipped` / `missed`)

| Status | Meaning | Calendar event |
|---|---|---|
| tentative | No signal yet; shown on the configured typical date | "Pre-emergent (estimated)" |
| projected | The trigger falls within the weather forecast horizon; date from the forecast | "Pre-emergent window ~Apr 12" |
| open | Trigger reached; notification sent | "Apply pre-emergent" (open date → expected close) |
| done | Logged (date picker or service) | "Pre-emergent applied" on the logged date |
| skipped | User said skip this season (`lawn_growth.skip_application`) | removed from upcoming; kept in history |
| missed | Window closed with nothing logged | "Pre-emergent window missed" |

All thresholds below are tunables with these defaults.

### 2.1 Pre-emergent (spring)

| | GeoDrops (Soil5 at D2, 2.5″) | GDD fallback |
|---|---|---|
| Heads-up — buy product | ≥ 47 °F and rising | ≥ 75 GDD50 |
| Open — apply now | ≥ 50 °F | ≥ 125 GDD50 |
| Late warning | ≥ 53 °F | **≥ 175 GDD50** |
| Germination expected | ≥ 55 °F | ≥ 200 GDD50 |
| Close (missed) | 14 days after germination expected, nothing logged | same |

The thresholds are anchored on germination at about 200 GDD50 (Purdue citing Calhoun; K-State) and 55 °F sustained soil temperature. The 175 late warning leaves room to apply and water it in before germination. With early-spring accumulation in New England of roughly 2–5 GDD50 a day, each step of 50 is about 1.5–3 weeks: heads-up to apply-now gives time to buy product, and apply-now to late warning is the main window. The soil column runs on the same spacing at 2.5″: 50 °F is the classic "apply" mark and 55 °F is germination. An alert set by GDD adds: "Estimated from air temperatures — confirm with a soil thermometer or put the probes in."

**Lawn-wide window.** One window for the whole lawn. With probes, the **warmest** area's Soil5 drives it (the first place crabgrass can germinate). Areas still on GDD use the lawn-wide GDD; if any area has probes and others don't, the earlier trigger wins. The status sensor and event say which area or source set it.

**Products.** Every herbicide log carries a product. Per-product settings; the defaults come from typical product labels for each active ingredient (rates and intervals vary by product, so the label actually used wins):

| Product | Type | Seeding blocked after application | Notes |
|---|---|---|---|
| Prodiamine | pre-emergent, blanket | 4 months (the label's interval at its lowest rate; higher rates need 5–6 months in the North, more in the South) | Typical first spring application. On new grass: not within 60 days of seeding or before the second mowing, whichever is longer |
| Dithiopyr | pre-emergent, blanket | 12 weeks (8 weeks when overseeding with perennial ryegrass) | Also controls very young crabgrass, so it still works after "germination expected". On new grass: only once well established |
| Mesotrione | pre + post, spot, per area | none — safe at seeding | Used with the fall overseed. Post-emergent use on new seedlings: warn if logged before the area's Seedlings ready |
| Other | as configured | setting | — |

Logging any product with a blocking period makes the window `done`.

**Second (split) application.** On by default (an early prodiamine plus a later dithiopyr is a common split). A reminder N weeks after the first is logged (default 7) suggests dithiopyr, a fixed-date event with no trigger. After "germination expected" with nothing logged, the late notification suggests dithiopyr for its early post-emergent action before the window is called missed.

**Seeding conflict.** The latest blocking product's period runs from its logged date. Inside it, `prep_overseed` and the overseed window warn ("Prodiamine applied Apr 8 — seeding blocked until Aug 8"). Logging a blocking product on an area that's establishing warns too, and so does logging prodiamine after Seedlings ready but within 60 days or 2 mows of the logged seeding. The window applies the same rule before anything goes down: while an area is inside prodiamine's new-grass wait (from its latest logged seeding and the mows since), the apply-now and late pushes name it and say to skip it or use dithiopyr there, whose label only asks for established turf; and while every area is inside it, the Pre-emergent product select suggests dithiopyr. Mesotrione never blocks.

### 2.2 Winterizer (late fall)

**Approved rule (D13).** Per area, since fertilizer logs are per area and their dates differ. Extension guidance (Purdue, Michigan State, Virginia Tech) agrees on: apply near or after the last mow of the year, while the grass is still green, before dormancy or frozen ground. Purdue puts that around early November. Opens when all hold:

1. **Growth has stopped needing mows:** the area is in the wind-down phase, and the last logged mow was followed by ≥ 10 days with no mow due (a likely last mow).
2. **Spacing:** ≥ 28 days since the last fertilizer.
3. **Still green:** not dormant (`low_gp_streak` below `dormant_days`), and where probes are still in, Soil5 ≥ 40 °F.

Closes (missed) when the area goes dormant, or Soil5 < 40 °F for 3 days. Typical date (tentative event): Nov 5.

A logged winterizer counts as fertilizer for the growth model, so its effect on growth stays as it is today.

Example: an area last fertilized on Oct 3 meets the spacing condition on Oct 31; one fertilized on Sep 21 meets it on Oct 19, leaving conditions 1 and 3 to decide.

### 2.3 Fall overseed window

- **Opens** when Soil5 falls below 70 °F after summer (GDD fallback: air T7 ≤ 72 °F and falling).
- **Ideal** while Soil5 is 60–70 °F.
- **Closes** when Soil5 < 55 °F, or air T7 < 50 °F.

Ties into the existing overseed feature:

- While the window is projected or open, the window event's description gives the latest seed date that `prep_overseed` can still reach from today (`overseed_earliest_date`), plus a "Start overseed prep" milestone.
- When a seeding is planned, `prep_overseed`'s seed date shows on the calendar and supersedes the window.
- An active seeding block from a pre-emergent shows in the window's description.
- When a seeding is logged, the event description suggests mesotrione at seeding, as a note only.
- Spring overseeding is out of scope (it conflicts with pre-emergent).

### 2.4 Post-emergent

Post-emergent timing depends on two things: the **season window** (weeds actively growing, grass not stressed) and the **spray day** (weather and mowing around the application). Per area, since post-emergent goes on as spot or area treatments.

**Products** (same product-aware log as §2.1; defaults from typical labels, except where marked):

| Product | Targets | Wait before seeding | New seedlings | Notes |
|---|---|---|---|---|
| Mesotrione | broadleaf, crabgrass, nimblewill | none | warn before Seedlings ready | Also pre-emergent; safe at seeding (§2.1) |
| Triclopyr ester | violets, ground ivy, clover, other hard broadleaf weeds | 3 weeks | block until the area has had 3 mows after Seedlings ready (the label: mowed 2 or 3 times) | Ester formulations turn volatile in heat: heat limit **80 °F** (also checked against tomorrow's high). The label sets no temperature limit, only warns of volatility in heat, so 80 °F is our margin. The label says not to water for 24 hours, which the 24 h rain-free check matches |
| Other | as configured | setting | setting | e.g. three-way (2,4-D + dicamba + MCPP), quinclorac |

**Season windows** (per area; the source rules from §1 apply):

| Window | Opens | Closes | Typical date (tentative) |
|---|---|---|---|
| Spring broadleaf | Soil5 ≥ 55 °F (GDD fallback: ≥ 250 GDD50) | heat: forecast highs ≥ 85 °F on 3 of the next 5 days, or Jun 30 | May 10 |
| Fall broadleaf (the most effective window: weeds are moving sugars to the roots) | after summer, air T7 ≤ 70 °F | dormancy, or air T7 < 45 °F | Sep 20 |
| Young crabgrass | 2 weeks after "germination expected" (§2.1) | about 6 weeks later, as crabgrass starts tillering | May 25 |

The young-crabgrass window only opens when the season's pre-emergent was missed, skipped, or logged late. Otherwise it stays quiet unless the user logs a breakthrough (`lawn_growth.flag_weeds`, below).

**Spray-day check**, inside an open window, run daily for today and tomorrow. A day is **good** when all of these hold:

1. **Temperature:** forecast high 60–85 °F (the product's heat limit wins when lower).
2. **Rain-free:** no rain expected for 24 h after a morning application (product setting; many products are rainfast sooner). From the hourly forecast's precipitation probability (< 30 %) when available, else the daily forecast.
3. **Wind:** hourly forecast wind < 10 mph in the morning, when the forecast includes wind; otherwise skipped and the notification says so.
4. **Mowing:** not mowed in the last 2 days, and Lawn Growth doesn't expect a mow due in the next 2 days. When a mow is due soon, the notice says "mow first, spray in 2 days".
5. **Grass not stressed:** not in heat hold or dormant, and soil not dry (the existing moisture factor).
6. **Seedlings:** the product's seedling rule passes for the area (table above).

Forecast fields vary by weather integration (hourly forecasts, wind and precipitation probability are all optional in HA). P4 starts by checking what common integrations return. Any check whose field is missing is skipped and named in the notification.

**After logging a post-emergent:**
- Mowing: a notification says "don't mow until <date>" (2 days, setting). **Mowing allowed** is held for that area for those 2 days so the robot stays off (setting, on by default, D15). The hold covers the logged area(s) only, starts at the logged date, and shows as the reason on Mowing allowed and in Mode. During establishment only Seedlings ready ever turns Mowing allowed back on, so the hold can only add to an existing hold, never release one.
- Seeding: the product's wait-before-seeding period feeds the same seeding-conflict check as pre-emergent (§2.1).
- The window stays open — post-emergent often takes a follow-up. Optional follow-up reminder N days later (product setting, default 21 days for triclopyr ester; off for mesotrione).

### 2.5 Logged history on the calendar

Shown as all-day events: seedings, fertilizer, PGR, winterizer, and herbicides by product ("Prodiamine — whole lawn", "Mesotrione spot — Backyard"). **Mows are off by default** (setting), because many robot-mower setups already log mows to a calendar.

Today fert/PGR records are pruned after 35 days (`store.py` `EVENT_RETENTION_DAYS`). The calendar needs a separate application log kept **400 days**. The growth model still only looks at the last 35.

## 3. Entities, services, notifications

**Lawn-wide**
- `calendar.lawn_growth_applications` (read-only in v1)
- `sensor.…_gdd` — GDD50 since the start date; attributes: start date, input source, last season's total
- `Pre-emergent` — enum status sensor; attributes: open/close/projected dates (an `estimated_date`, the typical date, while tentative), trigger value, source, the area that set it, and the seeding block's end date
- `Last pre-emergent` — date picker (logs for every area) plus a `Pre-emergent product` select it uses (prodiamine/dithiopyr/other), defaulting to the product the split reminder suggests. This follows the **Log mow height** pattern.

**Per area**
- `Soil temperature` — Soil5 (°F); attributes `source` (`geodrops`/`gdd`), valid days in the last 5, probes used
- `Winterizer`, `Overseed window`, `Post-emergent` — enum status sensors, same attributes. `Post-emergent` also gives which window is open (spring broadleaf / fall broadleaf / young crabgrass) and today's and tomorrow's spray-day verdict, with the failing check.
- `Good spray day` — binary sensor, on when today passes the spray-day check inside an open post-emergent window. Usable in automations, for example to skip irrigation.
- `Last winterizer` — date picker like Last fertilizer
- `Last post-emergent` — date picker plus a per-area `Post-emergent product` select (default mesotrione), replacing the earlier "Last spot herbicide"

**Services**
- `lawn_growth.log_event` gains kinds `winterizer` and `herbicide`. `herbicide` takes `product` and, with no `device_id`, applies to every area. The product decides whether the log counts as pre- or post-emergent (mesotrione counts as both).
- New `lawn_growth.skip_application` (`kind`, `device_id` where per area)
- New `lawn_growth.flag_weeds` (`device_id`, `target`: `broadleaf`/`crabgrass`): opens the matching post-emergent window early for that area when weeds show up outside it

**Notifications** (once per transition per window per season; tracked in the store)
- Pre-emergent: heads-up, open (apply now), late warning, missed
- Post-emergent: window open; then a "good spray day tomorrow" notice the evening before the first good day, at most once every 3 days per area while the window stays open and nothing is logged; "don't mow until <date>" after a log
- Winterizer: open only
- Overseed: open, plus "closing in ~7 days"
- When several areas cross the same transition on the same day, one message lists them

## 4. Calendar entity

- One lawn-wide entity, all-day events, using `async_get_events` and `event` (the next upcoming one).
- Events of the same kind and status falling on the same date across areas merge into one, e.g. "Apply pre-emergent — Front & Side, Back".
- **Summary:** short action. **Description:** status, trigger value, source, last updated.
- **Stable key:** `lawn_growth-{kind}-{season}-{area|all}-{event}`. A moved projection keeps its key; the phone-calendar writer (§5) uses it to write each firm event once.
- Built from one function `calendar_events(state) -> list[Event]`, shared by the entity and the phone-calendar writer.

## 5. Phone calendar (optional, HA calendar services)

Home Assistant can't publish a calendar as a subscription feed (checked against HA 2026.2: no core integration exports `.ics`), so Lawn Growth doesn't serve one. Instead it can write **firm events** into a calendar entity the user picks, with the core `calendar.create_event` service. With HA's Google Calendar integration those events reach the phone through Google (the Google Calendar app, or Apple Calendar with the Google account added); with CalDAV, through iCloud, Nextcloud and similar.

**Setting:** new optional lawn-wide **Copy events to calendars** under Lawn settings — one or more calendar entities that support creating events (selector filtered on `CalendarEntityFeature.CREATE_EVENT`, D16). Empty = nothing written.

**Firm events only.** Calendar entities can't be relied on to update events (Google supports create and delete, CalDAV only create), and `create_event` returns no event id. So Lawn Growth writes an event only once its date is final, and never needs to change it:

| Event | Written when | Date |
|---|---|---|
| "Apply pre-emergent" | window opens | open day, all-day |
| "Pre-emergent late — apply now" | late warning | that day |
| "Second pre-emergent (dithiopyr)" | first application logged | the reminder date (future) |
| "Winterizer window open" | window opens (per area) | that day |
| "Overseed window open" | window opens (per area) | that day |
| "Post-emergent window open" | window opens (per area) | that day |
| "Post-emergent follow-up" | an application with a follow-up setting is logged | logged date + follow-up days (future) |
| Logged application (e.g. "Prodiamine — whole lawn") | logged (date picker or service) | the logged date |

Not written: tentative and projected dates, spray-day notices, mows, seed dates from `prep_overseed` (they can be cancelled). Projections stay in Lawn Growth's own calendar entity (§4), where they can move freely.

**How it writes:**
- All-day events (`start_date`/`end_date`, end = start + 1 day). `create_event` rejects an end at or before the start, so zero-length events can't happen.
- Summary as in §4; the description carries the trigger value, source and `Lawn Growth key: <stable key>`.
- **No duplicates:** a ledger in the store maps each event's stable key (§4) to the date it was written; a key is written once. Same-day events across areas merge, as in §4.
- **Best-effort:** a failed write is logged and retried on the next run (up to 3 days), and never fails a run or blocks a notification. Reminders stay HA push notifications; the calendar entry is the record, not the alarm (the target calendar's default reminders, if any, still apply).

### 5.1 Release requirements

Lawn Growth is published for other people, so the phone calendar must work for installs that never set it up and for calendars other than Google:

- **Optional.** Lawn Growth works fully without a Phone calendar; the setting is empty by default and nothing else depends on it.
- **Any create-capable calendar.** Google Calendar, CalDAV (iCloud, Nextcloud, …), Local Calendar (stays inside HA) or any other integration whose entities support `CREATE_EVENT`. Nothing is Google-specific in code, strings or tests.
- **No manifest dependency.** `manifest.json` gains no `dependencies` or `after_dependencies` on `google`, `caldav` or any calendar integration. Only the core `calendar` service is called, and only when the setting is filled in.
- **Validated on save.** The settings step rejects an entity that doesn't exist or doesn't support creating events (`calendar_not_writable` error), on top of the selector filter.
- **Documented:**
  - README: a "Phone calendar" section — what gets written and what doesn't, which integrations work, that Google Calendar needs its own HA integration with read/write access (link to HA's Google Calendar docs for the application credentials), and the phone side (Google app, Apple Calendar with a Google or iCloud account).
  - Settings form: a `data_description` for the field saying it's optional, which events are written, and that the calendar's integration must allow creating events.
  - CHANGELOG entry for the release that adds it.
- **Repair issue when it breaks.** When the configured calendar entity is missing, or writes have failed on 3 consecutive days, raise an HA repair issue (`phone_calendar_unavailable`, translated) that names the calendar and says how to fix it (pick another calendar or clear the setting under Lawn settings). The issue clears on the next successful write or when the setting is cleared. Logged once, not every run.
- **Content:** events carry area names, products and trigger values only — nothing else from the install.

## 6. Storage and migration

- New store fields: lawn-wide GDD accumulator and last season's total; per area the current source and daily soil means with their usable-coverage fraction (last 7), windows keyed `(kind, season)`, notification flags; the 400-day application log; the phone-calendar ledger (stable key → date written, pending retries).
- Store version bump with migration. Existing fert/PGR events seed the application log.

## 7. Testing

- **Pure model:** reading usability for each Reading Quality and Probe Health state, the 75 % day-coverage rule, source switching (3-of-5 rule both ways, no repeat alert after a switch), replaying a recorded probe-install sequence (`training`/`calibrating` for ~1.5 days, then `good`/`ok`), GDD accumulation and back-fill, each window's state machine at its thresholds, the seeding conflict, the winterizer conditions, each spray-day check on its own (including skipping a check whose forecast field is missing), the seedling rules per product, and the Mowing allowed hold never releasing an establishment hold.
- **Phone calendar:** each firm event written exactly once (also across restarts and a moved projection), nothing written for tentative/projected dates, all-day start/end dates, a failed write retried and then dropped without failing the run, merged same-day events, the `calendar_not_writable` validation, the repair issue raised and cleared, and nothing called when the setting is empty; tested against a fake calendar with HA's real `create_event` schema.
- **HA tests:** calendar entity events, the new sensors, the new `log_event` kinds and `skip_application`, the options step, and daily runs out of season still accruing GDD.

## 8. Phasing

| Phase | Contents | Estimate |
|---|---|---|
| P1 ✅ | Soil source selection, GDD, Soil temperature and GDD sensors. No alerts. Ship **before Jan 1** so GDD counts from day one, or set the outdoor temperature sensor so it back-fills from statistics. | ~1 day |
| P2 ✅ | Windows, status sensors, notifications, application log, calendar entity | ~1.5–2 days |
| P3 ✅ | Phone calendar: the setting and its validation, the firm-event writer and its ledger, the repair issue, README/CHANGELOG (§5.1). | ~0.5–1 day |
| P4 ✅ | Post-emergent: windows, spray-day check, `Good spray day`, the Mowing allowed hold, `flag_weeds`. Starts by checking which forecast fields common weather integrations return. Needed by May (spring broadleaf). | ~1–1.5 days |

## P2 as built

Choices made where the spec left room (P3 and P4 build on these):

- **Products.** "Other" is two products, `other_pre_emergent` and `other_post_emergent`, so a log always says whether it counts as a pre-emergent. The Pre-emergent product select offers prodiamine, dithiopyr and other (pre-emergent). Any pre-emergent product makes the window done (other pre-emergent: 12-week seeding wait, a placeholder). Mesotrione and the post-emergents never close the pre-emergent window.
- **Seeding block** is the block that ends last among the area's logged products (not only the most recent log), so a short triclopyr wait doesn't hide a longer prodiamine one.
- **Seasons.** Pre-emergent is evaluated Jan 1 – Jun 30; from Jul 1 the next spring's window shows as tentative, and an unfinished window closes as missed. Winterizer and overseed are evaluated from Aug 1 to Dec 31. Fall soil passing back through 47–55 °F never touches the pre-emergent.
- **Pre-emergent notifications** are heads-up, apply now, late, germination expected (the dithiopyr suggestion) and missed. When several stages are new at once (a first run in late spring), only the latest is sent. The split reminder also pushes on its date.
- **Projections.** GDD from the forecast's daily means; soil from the least-squares trend of the last 7 daily soil means. The pre-emergent's expected close extrapolates the same signals past the forecast, else open + 35 days.
- **Winterizer** needs a logged mow (condition 1); dormancy or cold soil only closes it once it's open or the area has been in wind-down this season, so summer dormancy isn't a miss. Its source is `geodrops` or `air`.
- **Overseed window** exists for areas with an overseed target (cool-season). Without probes its source is `air` (7-day air mean), and the air-temperature note is added to its alerts too. A window that closes before it was seen open reads missed (silently). "Closing" is sent when the projected close is within 7 days. "Done" means a seeding logged during the season.
- **Notifications** are flagged on daily runs even without a Notify target, so setting one up later doesn't replay the season.
- **Calendar.** A done pre-emergent shows as its logged application ("Prodiamine — whole lawn", with the seeding block) rather than a separate "Pre-emergent applied" event. Skipped windows drop their upcoming events but keep the open/late events already passed. A log covering every area reads "whole lawn" and its key uses `all`; merged area events use `front+back`. Logged events use `applied-<date>` as the event part of the key and the product as the kind for herbicides. A planned seed date replaces the overseed window and its prep milestone.
- **Services.** `log_event` with no `device_id` logs for every area, for every kind. `skip_application` without `device_id` skips every area's window; logging afterwards still makes it done (there's no un-skip).
- **Storage.** Store 1.2 (minor bump, so an older version still loads it). The migration seeds the application log from the fert/PGR events and current seeding dates. Seedings are logged too; re-setting a seeding date replaces its log entry.
- **Probes back online** (§1.3, built after P4): sent on the daily run whose source for an area is `geodrops` when the previous daily run's was `gdd` (`AreaState.soil_source_last`, recorded on daily runs only, with or without a Notify target). An area is recorded only once its probes have been online (`geodrops`): new probes start out training, so their first GDD days aren't an outage, and a first run or an upgrade pushes nothing. Removing the probes from the area clears it. A run that couldn't read soil history (recorder not ready, or a read failed) records nothing, since its missing days say nothing about the probes. Areas switching on the same run share one message. The text says "application timing" rather than "pre-emergent tracking", since out of the pre-emergent season the switch moves the fall and post-emergent windows. A short outage doesn't push, because it doesn't change the source.

## P3 as built

- **Setting** `write_calendars` (a list, D16), on the first setup step and under Lawn settings. Validation rejects anything that isn't a calendar entity with `CREATE_EVENT` (from its state, or the entity registry when its integration isn't loaded): `calendar_not_writable`.
- **What's written:** `CalEvent.firm` events except mows and missed windows. On first adding a calendar, every such event on Lawn Growth's calendar is written (a backfill, up to the 400-day log).
- **Ledger per calendar, by atom.** Each area's part of an event is an atom (`lawn_growth-{kind}-{season}-{area}-{event}`; a whole-lawn log is one atom per area). When a second area's same-day log merges into an already-written event, only the new area is written ("Fertilizer — Front"), with its own key. A calendar removed from the setting keeps its ledger, so adding it back writes nothing twice. Entries for events no longer on the calendar are pruned after 30 days.
- **When it runs:** after every successful run (daily and after each log), once HA is running; its own lock keeps overlapping runs from writing twice. An unavailable calendar isn't called (an entity service call would skip it silently).
- **Retries.** A failed write stays pending and is retried every run. It's dropped after 3 days only while other writes to the same calendar succeed; while every write fails (the calendar is down), nothing is dropped, so the backlog lands once it works again.
- **Repair** `calendar_unavailable_<entity>` (translation `calendar_unavailable`), one per calendar: raised when the calendar doesn't exist, or writes have failed (or it was unavailable with writes due) on 3 consecutive days. Cleared by the next successful write, a run where it's reachable with nothing failing, or taking it out of the setting. The warning is logged when the issue is first raised.
- Store: `calendar_ledgers` (additive; no version bump).

## P4 as built

- **Forecast fields.** Checked against Home Assistant's `weatherflow_cloud` integration (its `weatherflow4py` forecast mapping): the daily forecast has high/low and precipitation probability but no wind; the hourly one has temperature, wind speed and gust, precipitation amount and probability. Other integrations vary (some have no hourly forecast, some no probability), so a separate read (`inputs.async_read_detail`) asks for both forecast types and takes whatever fields come back. Wind is converted from the entity's `wind_speed_unit` to mph.
- **Windows** are three kinds per area, `spring_broadleaf`, `fall_broadleaf` and `young_crabgrass`, in `model/postemergent.py`, run after the other windows each day. Their season is the calendar year. Statuses are `tentative`, `projected`, `open`, `done`, `skipped` and `closed`: a window stays open through applications and, when it closes, reads `done` if a post-emergent was logged in it, else `closed` (not `missed`: no weeds to spray isn't a miss, so it pushes nothing and adds no "missed" event).
- **Spring broadleaf** uses the area's Soil5, else lawn-wide GDD (≥ 250). Heat close: highs ≥ 85 °F on 3 of the next 5 forecast days. It closes after Jun 30 (from Jul 1). Projected like the pre-emergent (soil trend, forecast GDD).
- **Fall broadleaf** opens from **Aug 15** (the reading of "after summer"). Dormancy only closes it once open; a 7-day mean below 45 °F before it opened closes it silently.
- **Young crabgrass** exists only when the pre-emergent window reached "germination expected" and no pre-emergent was logged before that date (missed, skipped, still nothing, or logged on/after germination). It's projected for germination + 14 days, then open for 42 days. Before germination there's no window and nothing on the calendar.
- **`flag_weeds`** opens the target's window today (broadleaf: the spring window through Jun 30, else the fall window; crabgrass: young crabgrass). An open window is left as it is, a skipped one reopens, a `done`/`closed` one raises `window_ended`. A flagged open doesn't push "window open" (the user just said so).
- **`skip_application` `post_emergent`** skips the area's open windows, or else the next one to open.
- **Spray-day check** (`postemergent.spray_day`) for today and tomorrow while a window is open: temperature (high 60 °F to the product's limit; triclopyr ester 80 °F, also against the next day's high), rain (max hourly probability < 30 % from 08:00 for the product's rain-free hours, else the daily probability), wind (max hourly wind < 10 mph from 06:00 to 12:00), mowing (last mow ≥ 2 days before; no mow due within 2 days after), stress (dormant, heat hold for that day's high, water factor < 0.5), seedlings. Rain-free hours are per product (24 for all: triclopyr ester's label says not to water for 24 hours; the others are placeholders).
- **Seedling rules.** Before Seedlings ready every post-emergent fails the check and warns when logged. Triclopyr ester and Other then need 3 mows after Seedlings ready. `AreaState.seedlings_ready_on` records the press, since the first mow after it clears the seeding date; a press older than a year no longer counts. Installs that pressed it before P4 have no date, so the rule is satisfied once the seeding is cleared.
- **Mowing hold (D15)** is a tunable (`post_hold_mowing`, on), like the other P2 "settings": until the logged date + 2 days, Mowing allowed is off with the reason, Mode reads `spray_hold` (a new overlay mode; establishment and out-of-season keep their mode), Mow due is off and days until due is at least the days left. The "don't mow until" push goes out right after the log, whatever the hold setting.
- **Good spray day notice** goes out on the **daily run** (05:00 by default) for tomorrow, rather than an evening run: one notice a day ahead, without a second schedule. At most once every 3 days per area, only while nothing was logged in the open window. When only a coming mow fails the check, the notice says "mow first, spray 2 days later".
- **Follow-up** (triclopyr ester 21 days; off for mesotrione and Other) is a firm calendar event, key `lawn_growth-{product}-{year}-{area}-followup-<logged date>`, and a push on its date, once (`followups_notified` in the store). A follow-up already done by a later post-emergent, or one that came due over a week before the first run, is flagged without a push.
- **Calendar.** "Post-emergent (estimated, fall broadleaf)" while tentative, "Post-emergent window ~May 12 (spring broadleaf)" while projected, then "Post-emergent window open (spring broadleaf)" spanning open → close; the open event is firm, so P3 copies it. Logged post-emergents add "Don't mow until <date>." to their description.
- **Entities:** per area `Post-emergent` (shows the open window, else the next to open, else the last to end), `Good spray day`, `Last post-emergent` and `Post-emergent product` (default mesotrione, stored per area). There was no "Last spot herbicide" entity to replace.
- Store: `post_emergent_products`, `followups_notified`, and `flagged`/`spray_notified` on windows (additive; no version bump).

## Mirror mode (D17, as built)

- **Which calendars:** any target whose entity supports `DELETE_EVENT`. Updates use `UPDATE_EVENT` when supported (Local Calendar), else delete + create (Google, which supports create and delete). Create-only targets keep the §5 firm-event writer and its ledger.
- **How:** each run reads the target's events from today − 365 days to the later of today + 400 days and Lawn Growth's last event end (`async_get_events`), keeps those whose description has a `Lawn Growth key:` line, and diffs them against Lawn Growth's calendar by key (`calwriter.mirror_plan`): create the missing, update the changed (summary, description, dates), delete the rest and any duplicate of a key. Events without a key line are never touched. Lawn Growth's own events that end before the window aren't written, so an aged-out log stays in the target as a record.
- **HA API:** creates go through the `calendar.create_event` service; updates and deletes call the entity's `async_update_event` / `async_delete_event` (looked up via the calendar component), the way HA's own `calendar/event/update` and `calendar/event/delete` websocket commands do, with the update validated by `WEBSOCKET_EVENT_SCHEMA`. HA has no services for those.
- **Failures:** a failed read or change marks the day as failing and the next run diffs again (nothing to retry by hand). The repair rules are §5.1's: 3 consecutive failing days, cleared by a clean run.
- **Adoption:** events written by the firm-only writer (beta.8–beta.9) carry key lines, so a Local Calendar picked then is taken over in place; keys that no longer match Lawn Growth's calendar (an area log since merged into "whole lawn") are replaced.

## Later

- Learning the soil–air offset from fall/spring overlap to sharpen the GDD fallback (log it as a diagnostic in v1).
- Grub control, lime, aeration, spring overseeding.

## Open questions

None open.

Resolved against product labels for each active ingredient: the seeding waits (prodiamine 4 months, the label's lowest-rate interval; dithiopyr 12 weeks; triclopyr ester 3 weeks), prodiamine on new grass (60 days and 2 mows after seeding), and the triclopyr seedling rule (3 mows after Seedlings ready, the top of the label's 2–3). The triclopyr 80 °F limit and the 24 h rain-free time for mesotrione and Other stay as our margins: the labels checked give no number. Not modelled: prodiamine's rate (the wait grows with it) and its watering-in (0.2″ within 14 days).

Resolved 2026-10-17: scope (D5), probe depths (D7), `hardware_check` (D9), products (D10), blanket vs spot (D11), typical dates (D12), winterizer rule (D13), post-emergent products (D14), mowing hold (D15).

## Sources

- [Purdue — When should I apply my preemergence herbicide for crabgrass control?](https://turf.purdue.edu/when-should-i-apply-my-preemergence-herbicide-for-crabgrass-control/)
- [K-State — Methods of predicting crabgrass emergence](https://www.k-state.edu/news/turf/articles/2017/03/methods-of-predicting-crabgrass-emergence.html)
- [MSU GDDTracker — About](https://gddtracker.msu.edu/about)
- [Purdue — Fall fertilization](https://turf.purdue.edu/fall-fertilization/)
- [Virginia Tech — Late-fall fertilization](https://sites.ext.vt.edu/newsletter-archive/cses/2003-11/latefall.html)
