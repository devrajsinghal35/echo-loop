from typing import Callable, Any

class EventBus:
    """A simple synchronous publish/subscribe event bus."""
    def __init__(self):
        self._subscribers: dict[str, list[Callable[[Any], None]]] = {}

    def subscribe(self, topic: str, callback: Callable[[Any], None]) -> None:
        """Subscribe a callback to a specific topic."""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(callback)

    def publish(self, topic: str, data: Any) -> None:
        """Publish data to all subscribers of a specific topic."""
        if topic in self._subscribers:
            for callback in self._subscribers[topic]:
                callback(data)

# Global default bus instance for convenience
default_bus = EventBus()
