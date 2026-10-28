from capsule.storage import Store


class ReplyAudio:
    """Persisted browser reply level; physical ALSA output is configured by its client."""

    def __init__(self, store: Store, maximum: int = 75):
        self.store = store
        self.maximum = maximum
        self.volume = min(max(0, int(store.read().get("volume", 35))), maximum)

    def status(self):
        return {"volume": self.volume, "max_volume": self.maximum, "output": "browser_reply"}

    def set_volume(self, value: int):
        self.volume = min(self.maximum, max(0, value))
        self.store.write({"volume": self.volume})
        return self.status()
