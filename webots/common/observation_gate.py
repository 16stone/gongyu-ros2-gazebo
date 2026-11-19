"""A ground dispatch awaits a recent camera frame from the aerial observer."""


class ObservationGate:
    def __init__(self, max_age_ms, first_delay_ms, refresh_delay_ms=1000):
        self.max_age_ms = max_age_ms
        self.first_delay_ms = first_delay_ms
        self.refresh_delay_ms = refresh_delay_ms
        self.requested_at = None
        self.pending = None
        self.attempts = 0
        self.authorized = False

    def step(self, now, observation):
        if self.authorized:
            return None
        if self.requested_at is None:
            self.requested_at = now
            return "observation_requested", {"requested_at": now}
        if self.pending is not None:
            if now < self.pending["scheduled_delivery_ms"]:
                return None
            payload, self.pending = self.pending, None
            payload["arrived_at_ms"] = now
            payload["age_ms"] = now - payload["sample_t_ms"]
            if payload["age_ms"] <= self.max_age_ms:
                self.authorized = True
                return "observation_authorized", payload
            self.requested_at = now
            payload["refresh_requested_at"] = now
            return "observation_expired", payload
        if not observation or not observation.get("camera_bytes"):
            return None
        sampled = observation["t_ms"]
        if not self.requested_at <= sampled <= now:
            return None
        delay = self.refresh_delay_ms if self.attempts else self.first_delay_ms
        self.attempts += 1
        self.pending = {
            "attempt": self.attempts,
            "provider": "B3",
            "sample_t_ms": sampled,
            "frame_bytes": observation["camera_bytes"],
            "image_signature": observation.get("image_signature"),
            "scheduled_delivery_ms": now + delay,
            "max_age_ms": self.max_age_ms,
        }
        return "observation_queued", dict(self.pending)
