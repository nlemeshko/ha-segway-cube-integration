"""Shared support checks and delayed creation after reading capabilities."""

from homeassistant.core import callback

from .entity import CubeEntity


@callback
def add_supported_controls(entry, async_add_entities, definitions, entity_class):
    coordinator = entry.runtime_data
    added = set()

    @callback
    def add_available():
        entities = []
        for definition in definitions:
            if definition.key not in added and definition.supported(coordinator.data or {}):
                added.add(definition.key)
                entities.append(entity_class(coordinator, definition))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(add_available))
    add_available()


class CubeControlEntity(CubeEntity):
    def __init__(self, coordinator, definition):
        super().__init__(coordinator, definition.key)
        self.definition = definition
        self._attr_translation_key = definition.key
        self._attr_icon = definition.icon

    @property
    def available(self):
        data = self.coordinator.data or {}
        return super().available and self.definition.register in data and self.definition.supported(data)
