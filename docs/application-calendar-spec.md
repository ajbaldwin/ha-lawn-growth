# Application calendar — spec (draft)

Status: draft, 2026-10-17. P1 (§1) is built; P2–P4 are not.

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

**Products.** Every herbicide log carries a product. Per-product settings, with defaults that must be checked against the label actually used:

| Product | Type | Seeding blocked after application | Notes |
|---|---|---|---|
| Prodiamine | pre-emergent, blanket | 16 weeks | Typical first spring application |
| Dithiopyr | pre-emergent, blanket | 12 weeks | Also controls very young crabgrass, so it still works after "germination expected" |
| Mesotrione | pre + post, spot, per area | none — safe at seeding | Used with the fall overseed. Post-emergent use on new seedlings: warn if logged before the area's Seedlings ready |
| Other | as configured | setting | — |

Logging any product with a blocking period makes the window `done`.

**Second (split) application.** On by default (an early prodiamine plus a later dithiopyr is a common split). A reminder N weeks after the first is logged (default 7) suggests dithiopyr, a fixed-date event with no trigger. After "germination expected" with nothing logged, the late notification suggests dithiopyr for its early post-emergent action before the window is called missed.

**Seeding conflict.** The latest blocking product's period runs from its logged date. Inside it, `prep_overseed` and the overseed window warn ("Prodiamine applied Apr 8 — seeding blocked until Jul 29"). Logging a blocking product on an area that's establishing warns too. Mesotrione never blocks.

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

**Products** (same product-aware log as §2.1; defaults to check against the label):

| Product | Targets | Wait before seeding | New seedlings | Notes |
|---|---|---|---|---|
| Mesotrione | broadleaf, crabgrass, nimblewill | none | warn before Seedlings ready | Also pre-emergent; safe at seeding (§2.1) |
| Triclopyr ester | violets, ground ivy, clover, other hard broadleaf weeds | 4 weeks | block until the area has had 3 mows after Seedlings ready | Ester formulations turn volatile in heat: heat limit **80 °F** (also checked against tomorrow's high) |
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
- `Pre-emergent` — enum status sensor; attributes: open/close/projected dates, trigger value, source, the area that set it, and the seeding block's end date
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

**Setting:** new optional lawn-wide **Phone calendar** under Lawn settings — any calendar entity that supports creating events (selector filtered on `CalendarEntityFeature.CREATE_EVENT`). Empty = nothing written.

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
| P2 | Windows, status sensors, notifications, application log, calendar entity | ~1.5–2 days |
| P3 | Phone calendar: the setting and its validation, the firm-event writer and its ledger, the repair issue, README/CHANGELOG (§5.1). | ~0.5–1 day |
| P4 | Post-emergent: windows, spray-day check, `Good spray day`, the Mowing allowed hold, `flag_weeds`. Starts by checking which forecast fields common weather integrations return. Needed by May (spring broadleaf). | ~1–1.5 days |

## Later

- **Delete superseded events in Google** (e.g. a window later skipped). Needs the Google event's uid, which `create_event` doesn't return — find it with `calendar.get_events` by the key in the description — and the entity's delete method, which HA exposes only over the websocket API.
- Learning the soil–air offset from fall/spring overlap to sharpen the GDD fallback (log it as a diagnostic in v1).
- Grub control, lime, aeration, spring overseeding.

## Open questions

1. **Label defaults:** the seeding waits (prodiamine 16 weeks, dithiopyr 12 weeks, triclopyr ester 4 weeks), the triclopyr seedling rule (3 mows after Seedlings ready) and its 80 °F heat limit are placeholders. Check them against the product labels.

Resolved 2026-10-17: scope (D5), probe depths (D7), `hardware_check` (D9), products (D10), blanket vs spot (D11), typical dates (D12), winterizer rule (D13), post-emergent products (D14), mowing hold (D15).

## Sources

- [Purdue — When should I apply my preemergence herbicide for crabgrass control?](https://turf.purdue.edu/when-should-i-apply-my-preemergence-herbicide-for-crabgrass-control/)
- [K-State — Methods of predicting crabgrass emergence](https://www.k-state.edu/news/turf/articles/2017/03/methods-of-predicting-crabgrass-emergence.html)
- [MSU GDDTracker — About](https://gddtracker.msu.edu/about)
- [Purdue — Fall fertilization](https://turf.purdue.edu/fall-fertilization/)
- [Virginia Tech — Late-fall fertilization](https://sites.ext.vt.edu/newsletter-archive/cses/2003-11/latefall.html)
