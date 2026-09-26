"""Config flow for Lawn Growth: lawn settings, then mowing areas via an options hub."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import (
    EntitySelector, EntitySelectorConfig, NumberSelector, NumberSelectorConfig,
    NumberSelectorMode, SelectSelector, SelectSelectorConfig, SelectSelectorMode,
    TextSelector, TimeSelector)
from homeassistant.util import slugify

from . import const as c
from .model.presets import DEFAULT_PRESET, PRESETS


def _inches() -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(min=0.5, max=8.0, step=0.05,
                                               unit_of_measurement="in",
                                               mode=NumberSelectorMode.BOX))


def _number(lo: float, hi: float, step: float) -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(min=lo, max=hi, step=step,
                                               mode=NumberSelectorMode.BOX))


def _suggest(value) -> dict:
    return {"suggested_value": value}


def _notify_choices(hass, current: str | None) -> list:
    """Callable notify services. `notify.send_message` is left out (it is an entity
    service that needs a target); the saved choice stays listed even if its service
    is gone, so the settings can still be saved."""
    choices = {f"notify.{n}" for n in hass.services.async_services_for_domain("notify")
               if n != "send_message"}
    if current:
        choices.add(current)
    return sorted(choices)


def _lawn_schema(hass, values: dict) -> vol.Schema:
    notify = _notify_choices(hass, values.get(c.CONF_NOTIFY))
    return vol.Schema({
        vol.Required(c.CONF_WEATHER, default=values.get(c.CONF_WEATHER, vol.UNDEFINED)):
            EntitySelector(EntitySelectorConfig(domain="weather")),
        vol.Optional(c.CONF_SEASON, description=_suggest(values.get(c.CONF_SEASON))):
            EntitySelector(EntitySelectorConfig(domain=["input_boolean", "switch",
                                                        "binary_sensor"])),
        vol.Optional(c.CONF_NOTIFY, description=_suggest(values.get(c.CONF_NOTIFY))):
            SelectSelector(SelectSelectorConfig(options=notify,
                                                mode=SelectSelectorMode.DROPDOWN)),
        vol.Required(c.CONF_RUN_TIME, default=values.get(c.CONF_RUN_TIME, c.DEFAULT_RUN_TIME)):
            TimeSelector(),
    })


def _clean(user_input: dict) -> dict:
    return {k: v for k, v in user_input.items() if v not in (None, "", [])}


def _basics_schema(default_name: str, default_grass: str = DEFAULT_PRESET) -> vol.Schema:
    return vol.Schema({
        vol.Required(c.AREA_NAME, default=default_name): TextSelector(),
        vol.Required(c.AREA_GRASS, default=default_grass): SelectSelector(SelectSelectorConfig(
            options=list(PRESETS), translation_key="grass", mode=SelectSelectorMode.DROPDOWN)),
    })


def _preset_defaults(grass: str) -> dict:
    p = PRESETS[grass]
    return {c.AREA_CURVE: p.curve, c.AREA_CUT_MIN: p.cut_min_in, c.AREA_CUT_MAX: p.cut_max_in,
            c.AREA_OVERSEED_TARGET: p.overseed_target_in}


def _details_schema(d: dict, *, grass: str, locations: list | None) -> vol.Schema:
    custom = grass == "custom"
    fields: dict = {}
    if custom:
        fields[vol.Required(c.AREA_CURVE, default=d[c.AREA_CURVE])] = SelectSelector(
            SelectSelectorConfig(options=["cool", "warm"], translation_key="curve"))
    fields[vol.Required(c.AREA_CUT_MIN, default=d[c.AREA_CUT_MIN])] = _inches()
    fields[vol.Required(c.AREA_CUT_MAX, default=d[c.AREA_CUT_MAX])] = _inches()
    if custom or PRESETS[grass].curve == "cool":
        fields[vol.Optional(c.AREA_OVERSEED_TARGET,
                            description=_suggest(d.get(c.AREA_OVERSEED_TARGET)))] = _inches()
    fields[vol.Optional(c.AREA_MOISTURE, default=d.get(c.AREA_MOISTURE, []))] = EntitySelector(
        EntitySelectorConfig(domain="sensor", multiple=True))
    fields[vol.Required(c.AREA_WILTING, default=d.get(c.AREA_WILTING, 40.0))] = _number(0, 100, 0.5)
    fields[vol.Required(c.AREA_COMFORTABLE, default=d.get(c.AREA_COMFORTABLE, 67.0))] = \
        _number(0, 100, 0.5)
    fields[vol.Optional(c.AREA_MOW_SOURCE, description=_suggest(d.get(c.AREA_MOW_SOURCE)))] = \
        EntitySelector(EntitySelectorConfig())
    fields[vol.Required(c.AREA_MOW_MODE, default=d.get(c.AREA_MOW_MODE, c.MOW_MODE_INCREASES))] = \
        SelectSelector(SelectSelectorConfig(options=[c.MOW_MODE_INCREASES, c.MOW_MODE_ANY],
                                            translation_key="mow_mode"))
    if locations is not None:
        fields[vol.Optional(c.AREA_LOCATIONS, default=d.get(c.AREA_LOCATIONS, []))] = \
            SelectSelector(SelectSelectorConfig(options=locations, multiple=True,
                                                custom_value=True))
    fields[vol.Required(c.AREA_MAX_RATE, default=d.get(c.AREA_MAX_RATE, 6.5))] = _number(0.5, 20, 0.1)
    return vol.Schema(fields)


def _validate(ui: dict) -> dict:
    errors = {}
    if ui[c.AREA_CUT_MIN] >= ui[c.AREA_CUT_MAX]:
        errors[c.AREA_CUT_MAX] = "cut_range"
    target = ui.get(c.AREA_OVERSEED_TARGET)
    if target is not None and target >= ui[c.AREA_CUT_MAX]:
        errors[c.AREA_OVERSEED_TARGET] = "overseed_target"
    if ui[c.AREA_WILTING] >= ui[c.AREA_COMFORTABLE]:
        errors[c.AREA_COMFORTABLE] = "moisture_band"
    return errors


def _build_area(key: str, name: str, grass: str, ui: dict) -> dict:
    return {
        c.AREA_KEY: key, c.AREA_NAME: name, c.AREA_GRASS: grass,
        c.AREA_CURVE: ui.get(c.AREA_CURVE, PRESETS[grass].curve),
        c.AREA_CUT_MIN: float(ui[c.AREA_CUT_MIN]), c.AREA_CUT_MAX: float(ui[c.AREA_CUT_MAX]),
        c.AREA_OVERSEED_TARGET: ui.get(c.AREA_OVERSEED_TARGET),
        c.AREA_MOISTURE: list(ui.get(c.AREA_MOISTURE, [])),
        c.AREA_WILTING: float(ui[c.AREA_WILTING]),
        c.AREA_COMFORTABLE: float(ui[c.AREA_COMFORTABLE]),
        c.AREA_MOW_SOURCE: ui.get(c.AREA_MOW_SOURCE) or None,
        c.AREA_MOW_MODE: ui[c.AREA_MOW_MODE],
        c.AREA_LOCATIONS: list(ui.get(c.AREA_LOCATIONS, [])),
        c.AREA_MAX_RATE: float(ui[c.AREA_MAX_RATE]),
    }


def _unique_key(name: str, existing: set) -> str:
    base = slugify(name) or "area"
    key, n = base, 2
    while key in existing:
        key, n = f"{base}_{n}", n + 1
    return key


class _AreaSteps:
    """area_basics -> area_details, shared by the config flow and the options flow."""
    _area_name: str = ""
    _area_grass: str = DEFAULT_PRESET
    _editing_key: str | None = None

    def _existing_areas(self) -> list:
        return []

    def _mower_locations(self) -> list | None:
        return None

    async def _async_area_done(self, area: dict):
        raise NotImplementedError

    async def async_step_area_basics(self, user_input=None):
        errors: dict = {}
        if user_input is not None:
            name = user_input[c.AREA_NAME].strip()
            if name:
                self._area_name = name
                self._area_grass = user_input[c.AREA_GRASS]
                return await self.async_step_area_details()
            errors[c.AREA_NAME] = "invalid_name"
            default_name, default_grass = "", user_input[c.AREA_GRASS]
        elif self._editing_key:
            default_name, default_grass = self._area_name, self._area_grass
        else:
            default_name, default_grass = ("" if self._existing_areas() else "Lawn"), DEFAULT_PRESET
        return self.async_show_form(
            step_id="area_basics", data_schema=_basics_schema(default_name, default_grass),
            errors=errors)

    async def async_step_area_details(self, user_input=None):
        areas = self._existing_areas()
        editing = next((a for a in areas if a[c.AREA_KEY] == self._editing_key), None)
        if editing is not None:
            defaults = dict(editing)
            if editing[c.AREA_GRASS] != self._area_grass:
                defaults.update(_preset_defaults(self._area_grass))
        else:
            defaults = _preset_defaults(self._area_grass)
        errors: dict = {}
        if user_input is not None:
            errors = _validate(user_input)
            taken = {v for a in areas if a[c.AREA_KEY] != self._editing_key
                     for v in a.get(c.AREA_LOCATIONS, [])}
            if taken & set(user_input.get(c.AREA_LOCATIONS, [])):
                errors[c.AREA_LOCATIONS] = "location_in_use"
            if not errors:
                key = self._editing_key or _unique_key(self._area_name,
                                                       {a[c.AREA_KEY] for a in areas})
                return await self._async_area_done(
                    _build_area(key, self._area_name, self._area_grass, user_input))
            defaults.update(user_input)
        return self.async_show_form(
            step_id="area_details",
            data_schema=_details_schema(defaults, grass=self._area_grass,
                                        locations=self._mower_locations()),
            errors=errors, description_placeholders={"name": self._area_name})


class LawnGrowthConfigFlow(_AreaSteps, config_entries.ConfigFlow, domain=c.DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._lawn: dict = {}

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self._lawn = _clean(user_input)
            return await self.async_step_area_basics()
        return self.async_show_form(step_id="user", data_schema=_lawn_schema(self.hass, {}))

    async def _async_area_done(self, area: dict):
        return self.async_create_entry(title="Lawn Growth", data={},
                                       options={**self._lawn, c.CONF_AREAS: [area]})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return LawnGrowthOptionsFlow()


class LawnGrowthOptionsFlow(_AreaSteps, config_entries.OptionsFlowWithReload):
    def _existing_areas(self) -> list:
        return [dict(a) for a in self.config_entry.options.get(c.CONF_AREAS, [])]

    def _mower_locations(self) -> list | None:
        mower = self.config_entry.options.get(c.CONF_MOWER)
        if not mower:
            return None
        st = self.hass.states.get(mower.get(c.MOWER_LOCATION, ""))
        known = set(st.attributes.get("options", [])) if st else set()
        used = {v for a in self._existing_areas() for v in a.get(c.AREA_LOCATIONS, [])}
        return sorted(known | used)

    def _save(self, **changes):
        return self.async_create_entry(title="", data={**self.config_entry.options, **changes})

    def _area_choice(self) -> vol.Schema:
        return vol.Schema({vol.Required("area"): vol.In(
            {a[c.AREA_KEY]: a[c.AREA_NAME] for a in self._existing_areas()})})

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=[
            "area_basics", "edit_area", "remove_area", "settings", "mower"])

    async def _async_area_done(self, area: dict):
        areas = self._existing_areas()
        if any(a[c.AREA_KEY] == area[c.AREA_KEY] for a in areas):
            areas = [area if a[c.AREA_KEY] == area[c.AREA_KEY] else a for a in areas]
        else:
            areas.append(area)
        return self._save(**{c.CONF_AREAS: areas})

    async def async_step_edit_area(self, user_input=None):
        if user_input is not None:
            chosen = next(a for a in self._existing_areas() if a[c.AREA_KEY] == user_input["area"])
            self._editing_key = chosen[c.AREA_KEY]
            self._area_name = chosen[c.AREA_NAME]
            self._area_grass = chosen[c.AREA_GRASS]
            return await self.async_step_area_basics()
        return self.async_show_form(step_id="edit_area", data_schema=self._area_choice())

    async def async_step_remove_area(self, user_input=None):
        areas = self._existing_areas()
        if len(areas) <= 1:
            return self.async_abort(reason="last_area")
        if user_input is not None:
            key = user_input["area"]
            registry = dr.async_get(self.hass)
            device = registry.async_get_device(
                identifiers={(c.DOMAIN, f"{self.config_entry.entry_id}_{key}")})
            if device is not None:
                registry.async_remove_device(device.id)
            return self._save(**{c.CONF_AREAS: [a for a in areas if a[c.AREA_KEY] != key]})
        return self.async_show_form(step_id="remove_area", data_schema=self._area_choice())

    async def async_step_settings(self, user_input=None):
        if user_input is not None:
            opts = {k: v for k, v in self.config_entry.options.items()
                    if k not in (c.CONF_SEASON, c.CONF_NOTIFY)}
            opts.update(_clean(user_input))
            return self.async_create_entry(title="", data=opts)
        return self.async_show_form(step_id="settings",
                                    data_schema=_lawn_schema(self.hass, self.config_entry.options))

    async def async_step_mower(self, user_input=None):
        current = self.config_entry.options.get(c.CONF_MOWER) or {}
        errors: dict = {}
        if user_input is not None:
            if not user_input.get(c.MOWER_ACTIVITY):
                opts = {k: v for k, v in self.config_entry.options.items() if k != c.CONF_MOWER}
                opts[c.CONF_AREAS] = [{**a, c.AREA_LOCATIONS: []} for a in self._existing_areas()]
                return self.async_create_entry(title="", data=opts)
            for key in (c.MOWER_WORKING, c.MOWER_BLADE, c.MOWER_LOCATION):
                if not user_input.get(key):
                    errors[key] = "required_with_mower"
            if not errors:
                return self._save(**{c.CONF_MOWER: {
                    c.MOWER_ACTIVITY: user_input[c.MOWER_ACTIVITY],
                    c.MOWER_WORKING: list(user_input[c.MOWER_WORKING]),
                    c.MOWER_BLADE: user_input[c.MOWER_BLADE],
                    c.MOWER_LOCATION: user_input[c.MOWER_LOCATION],
                    c.MOWER_GRACE: int(user_input[c.MOWER_GRACE]),
                    c.MOWER_MIN_AREA: int(user_input[c.MOWER_MIN_AREA]),
                }})
            current = {**current, **user_input}
        working = sorted(set(current.get(c.MOWER_WORKING, [])) | {"mowing"})
        schema = vol.Schema({
            vol.Optional(c.MOWER_ACTIVITY, description=_suggest(current.get(c.MOWER_ACTIVITY))):
                EntitySelector(EntitySelectorConfig(domain=["sensor", "lawn_mower", "select"])),
            vol.Optional(c.MOWER_WORKING, default=current.get(c.MOWER_WORKING, [])):
                SelectSelector(SelectSelectorConfig(options=working, multiple=True,
                                                    custom_value=True)),
            vol.Optional(c.MOWER_BLADE, description=_suggest(current.get(c.MOWER_BLADE))):
                EntitySelector(EntitySelectorConfig(domain=["sensor", "number"])),
            vol.Optional(c.MOWER_LOCATION, description=_suggest(current.get(c.MOWER_LOCATION))):
                EntitySelector(EntitySelectorConfig(domain=["sensor", "select"])),
            vol.Required(c.MOWER_GRACE,
                         default=current.get(c.MOWER_GRACE, c.DEFAULT_GRACE_MINUTES)):
                _number(1, 120, 1),
            vol.Required(c.MOWER_MIN_AREA,
                         default=current.get(c.MOWER_MIN_AREA, c.DEFAULT_MIN_AREA_MINUTES)):
                _number(1, 120, 1),
        })
        return self.async_show_form(step_id="mower", data_schema=schema, errors=errors)
