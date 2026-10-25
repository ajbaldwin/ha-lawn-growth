# Changelog

## 0.1.0-beta.11 — Herbicide label defaults
- **Seeding waits now follow the product labels.** Prodiamine blocks seeding for 4 months instead of 16 weeks (its label's interval at the lowest rate; a higher rate needs longer), and triclopyr ester for 3 weeks instead of 4.
- **Prodiamine on new grass now warns.** Logging it on grass seeded less than 60 days ago, or mowed fewer than 2 times since seeding, sends a warning, as its label says.
- **The pre-emergent notifications name any area that's too new for prodiamine** and say to skip it or use dithiopyr there, and when every area is too new the Pre-emergent product select suggests dithiopyr.
- **A notification says when an area's soil probes are back online**, once Lawn Growth switches that area from growing degree days back to soil temperature (about 3 days of good readings after the probes go back in).

## 0.1.0-beta.10 — Calendars kept in step
- **Calendars that can edit events now mirror Lawn Growth's calendar.** A Local Calendar or Google Calendar picked under Copy events to calendars now shows everything on Lawn Growth's own calendar, estimates included, and Lawn Growth moves an estimate when its date changes and removes events that no longer apply, such as a skipped window.
- **Your own events are safe.** Lawn Growth only changes events it added (the ones whose description ends with a "Lawn Growth key" line), and leaves events older than a year in place as a record.
- **Calendars that can only add events** still get firm events only, each added once.
- **The README lists what Lawn Growth needs**, including internet access for the weather forecast.

## 0.1.0-beta.9 — Post-emergent
- **Post-emergent windows per mowing area:** spring broadleaf (soil 55 °F, or 250 growing degree days without probes; closes on a forecast heat spell or after Jun 30), fall broadleaf (from Aug 15, once the 7-day air mean is 70 °F or lower; the most effective time) and young crabgrass (two weeks after crabgrass germination, only when the pre-emergent was missed, skipped or late). A new **Post-emergent** sensor shows the window. It stays open after you spray, because weeds often need a follow-up.
- **Good spray day.** Inside an open window, Lawn Growth checks today and tomorrow for temperature (60–85 °F; triclopyr ester 80 °F), rain, morning wind, mowing, grass stress and new seedlings. The new **Good spray day** binary sensor turns on when today passes. A notification says when tomorrow looks good, at most every 3 days per area. Weather integrations that don't forecast wind or rain chance skip those checks and say so.
- **Log a post-emergent** with the new per-area **Last post-emergent** date and **Post-emergent product** select (default mesotrione), or `lawn_growth.log_event`. A notification says not to mow for 2 days, and **Mowing allowed** turns off for that area until then, so a robot mower stays off. Mode reads "Hold after spraying". During establishment, Seedlings ready is still the only way to turn mowing back on. Triclopyr ester gets a follow-up reminder 21 days later.
- **`lawn_growth.flag_weeds`** opens a broadleaf or crabgrass window early when weeds show up outside one. `lawn_growth.skip_application` gains `post_emergent`.
- "Post-emergent window open" and "Post-emergent follow-up" appear on the Applications calendar and are copied to your other calendars.

## 0.1.0-beta.8 — Copy events to your calendars
- **Copy application events to other calendars.** A new optional **Copy events to calendars** setting under Lawn settings takes one or more calendars that can create events, such as a Local Calendar or Google Calendar (with Home Assistant's Google Calendar integration set up with read/write access, the events reach your phone). Lawn Growth adds each firm event there once, as an all-day event: a window opening, the pre-emergent late warning, the second pre-emergent reminder, and every logged application. Tentative and projected dates stay on Lawn Growth's own calendar. Adding a calendar copies the events already logged; nothing is ever copied twice. If a calendar goes missing or can't take events for 3 days, a repair appears and the waiting events are added once it works again. Leave the setting empty and nothing changes.
- **Tentative windows show their date.** The Pre-emergent, Winterizer and Overseed window sensors gain an `estimated_date` attribute while tentative: the typical date (Apr 10, Nov 5, Aug 25), the same one the calendar shows.

## 0.1.0-beta.7 — Application calendar and startup resilience
- **Application windows for pre-emergent, winterizer and fall overseeding**, timed from soil temperature (or growing degree days and air temperatures without probes). New **Pre-emergent** (lawn-wide), **Winterizer** and **Overseed window** (per area) sensors read tentative, projected, open, done, skipped or missed, with the dates, trigger value and source as attributes.
- **Notifications** when a window opens, plus pre-emergent heads-up, late, germination-expected and missed alerts and an overseed closing-soon alert. Once per window per season; areas crossing together share one message.
- **Applications calendar** (`calendar.lawn_growth_applications`): upcoming windows and everything logged — seedings, fertilizer, PGR, winterizer and herbicides — kept for 400 days, separate from the 35-day records the growth model uses.
- **Product-aware herbicide logging.** `lawn_growth.log_event` gains kinds `winterizer` and `herbicide` (with a `product`); leave `device_id` empty to log for every area. A pre-emergent blocks seeding for its label period, and Prepare for overseeding warns inside it. New **Last pre-emergent** date picker and **Pre-emergent product** select, and a per-area **Last winterizer** picker. A winterizer counts as fertilizer for growth.
- **`lawn_growth.skip_application`** skips this season's pre-emergent, winterizer or overseed window.
- The `lawn_growth.log_event` service is now called "Log an application".
- **Lawn Growth no longer fails to load when the weather entity isn't ready at startup.** Cloud weather integrations can come up after Lawn Growth; before, that showed Lawn Growth as failed in Devices & services until it was reloaded. Now it loads, its sensors stay unavailable briefly, and it runs as soon as the weather entity comes up, retrying every 15 minutes until a forecast arrives. A missed daily run still sends its notifications once it succeeds.
- **Adding or changing the outdoor temperature sensor recounts growing degree days.** Before, a sensor set after the first run only counted new days, leaving a partial total counted from the forecast. Now the season is recounted from the sensor's history whenever the sensor is added or changed.

## 0.1.0-beta.6 — Soil temperature and growing degree days
- **Soil temperature per mowing area**, from the GeoDrops probes behind its soil moisture sensors, at a depth you pick (1.5″, 2.5″ default, 3.5″). A reading counts only while GeoDrops reports good quality and the probe isn't calibrating, so a freshly installed or pulled probe drops out by itself and comes back once GeoDrops trusts it again. The sensor shows the last 5 days' mean once at least 3 of them are complete.
- **Growing degree days** (base 50 °F, from Jan 1), lawn-wide. Set an **Outdoor temperature sensor** under Lawn settings to use observed highs and lows (back-filled from its history); otherwise the weather forecast is used. Set the sensor right after updating: the back-fill runs once, on the first daily run after the update.
- Groundwork for the application calendar (`docs/application-calendar-spec.md`); no new notifications yet.

## 0.1.0-beta.5 — Seedlings ready decides
- **Mowing seedlings no longer ends establishment early.** Before, logging any mow after the seeding date cleared the seeding date. Now a mow only ends establishment after you press Seedlings ready. Mows before that still update Last mow and the cut height, but the area stays in establishment, so Mowing allowed stays off. To end establishment yourself, press Seedlings ready; the next mow then returns the area to normal.
- **Only Seedlings ready allows mowing on new seed.** Before, the model's seedling-height estimate could switch an area to first mow ready on its own, which turned Mowing allowed on (and could start a robot mower). Now the estimate only notifies you ("seedlings look ready… press Seedlings ready") and Overseed status reads "seedlings look ready". Mowing allowed stays off until you press the button.
- **Choose the height when you log a mow.** Each mowing area has a new **Log mow height** number. Log mow, the Last mow date picker and a mow counter record that height. Until you set it, it follows the last cut height, as before.

## 0.1.0-beta.4 — Fewer, safer buttons
- **Removed the Log seeding, Log fertilizer and Log PGR buttons.** The Seeding date, Last fertilizer and Last PGR date entities from beta.3 do the same job with the date in view. Log seeding was also easy to tap by mistake: it reset an area's seeding date to today, restarting establishment. Upgrading removes the old button entities; if a dashboard or automation used them, switch it to the date entity or the matching service (`lawn_growth.log_seeding`, `lawn_growth.log_event`), which are unchanged.
- **Log mow and Seedlings ready stay.** Log mow is still the one-tap way to record today's mow.

## 0.1.0-beta.3 — Seeding dates
- **Pick dates for mows, seeding, fertilizer and PGR from a calendar.** Each mowing area now has Seeding date, Last mow, Last fertilizer and Last PGR pickers, so you're not limited to logging them as today. Seeding date corrects the stored date directly; the others log on the date you pick. Fixes the Log seeding button silently overwriting an earlier, correct seeding date.
- **Overseed status now covers establishment.** After a seeding, it reads "establishing" while the seedlings grow in and "first mow ready" once they're tall enough, instead of "inactive".
- Overseed status gains attributes: seeding date, days since seeding, estimated seedling height and the first-mow target height.

## 0.1.0-beta.2 — Clearer setup
- **Weather picked for you.** Initial setup now pre-selects `weather.home` or `weather.forecast_home` when one exists, or your only weather entity, so most people won't need to touch that field.
- **What a mowing area is, spelled out**, with an example, both when adding your first one and from the Configure menu — plus a note that the device Home Assistant creates for it doesn't need to be assigned to a Home Assistant area.
- **Friendlier mow-counter wording.** The field for mowers without an integration is now called "Mow counter (mowers without an integration)" with a plain-language description of what it's for.
- **"Mower" renamed to "Mower settings"** in the Configure menu, so it reads as configuration rather than a status page.
- **Mower settings pre-fill themselves.** With exactly one lawn-mower entity, Configure → Mower settings now suggests it as the activity entity, defaults the working states to mowing and paused, and — from sensors on the same device — suggests a blade-height and a location sensor. Nothing is saved until you submit the form.
- **Clearer location-mapping help**, with a worked example for mapping a mower's location sensor values to your mowing areas.

## 0.1.0-beta.1 — First beta
- **Mowing advice from growing conditions.** Each mowing area gets a growth model driven by your weather forecast and (optionally) soil moisture: how much the grass has grown since the last cut, when the next mow is due, and whether heat or dormancy should hold it off.
- **Seasonal cut heights.** A recommended height that follows the season — taller in summer stress, lower for spring green-up and the fall wind-down — within the range for your grass type, and never more than a third off in one mow.
- **Knows what was actually cut.** Link a robot mower and Lawn Growth logs each run itself, with the blade height it really used, however the run was started. Otherwise log mows with a button or a service.
- **Overseeding.** Steps the height down ahead of a seed date, then holds mowing until the seedlings are ready and tells you the first-mow height.
- **Fertilizer and PGR logging** adjust the growth model for the weeks they are active.
- Optional push notifications for mow due, first mow ready and overseed steps.
