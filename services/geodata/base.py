from abc import ABC, abstractmethod


class GeodataError(ValueError):
    """A safe, actionable provider/input error; never includes response bodies."""


class GeodataProvider(ABC):
    @abstractmethod
    def health_check(self, refresh=False): ...

    @abstractmethod
    def get_capabilities(self, refresh=False): ...

    @abstractmethod
    def list_services(self): ...

    @abstractmethod
    def list_layers(self): ...

    @abstractmethod
    def get_layer_metadata(self, layer_id): ...

    @abstractmethod
    def get_features(self, layer_id, bbox=None, geometry=None, limit=50): ...
