# Changelog

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
