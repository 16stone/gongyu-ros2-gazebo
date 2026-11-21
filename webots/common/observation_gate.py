"""A ground dispatch awaits a recent camera frame from the aerial observer."""


from random import Random


class ObservationLink:
    """Deterministic software transport faults for camera report delivery."""

    def __init__(self, *, loss_rate=0.0, seed=0, blackout=None):
        if not 0 <= loss_rate <= 1:
            raise ValueError("observation loss rate must be between zero and one")
        if blackout is not None and not (len(blackout) == 2 and 0 <= blackout[0] < blackout[1]):
            raise ValueError("observation blackout must have increasing nonnegative times")
        self.loss_rate = loss_rate
        self.random = Random(seed)
        self.blackout = blackout

    def failure_at(self, now):
        if self.blackout is not None and self.blackout[0] <= now < self.blackout[1]:
            return "blackout"
        if self.loss_rate and self.random.random() < self.loss_rate:
            return "random_loss"
        return None


class ObservationGate:
    def __init__(self, max_age_ms, first_delay_ms, refresh_delay_ms=1000, *, retry_on_expiry=True, link=None,
                 verifier=None):
        self.max_age_ms = max_age_ms
        self.first_delay_ms = first_delay_ms
        self.refresh_delay_ms = refresh_delay_ms
        self.requested_at = None
        self.pending = None
        self.attempts = 0
        self.authorized = False
        self.retry_on_expiry = retry_on_expiry
        self.rejected = False
        self.link = link
        # optional callable(record) -> bool; frames that fail it are dropped
        self.verifier = verifier
        self.forgeries = []

    def step(self, now, observation):
        if self.authorized or self.rejected:
            return None
        if self.requested_at is None:
            self.requested_at = now
            return "observation_requested", {"requested_at": now}
        if self.pending is not None:
            if now < self.pending["scheduled_delivery_ms"]:
                return None
            payload = self.pending
            if "transport_failure" in payload:
                if now < payload["sample_t_ms"] + self.max_age_ms:
                    return None
                payload["timeout_at_ms"] = now
                outcome = "observation_timeout"
            else:
                failure = self.link.failure_at(now) if self.link is not None else None
                if failure is not None:
                    payload.update(transport_failure=failure, dropped_at_ms=now)
                    return "observation_transport_dropped", dict(payload)
                payload["arrived_at_ms"] = now
                payload["age_ms"] = now - payload["sample_t_ms"]
                if payload["age_ms"] <= self.max_age_ms:
                    self.authorized = True
                    self.pending = None
                    return "observation_authorized", payload
                outcome = "observation_expired"
            self.pending = None
            if self.retry_on_expiry:
                self.requested_at = now
                payload["refresh_requested_at"] = now
            else:
                self.rejected = True
            return outcome, payload
        if not observation or not observation.get("camera_bytes"):
            return None
        sampled = observation["t_ms"]
        if not self.requested_at <= sampled <= now:
            return None
        if self.verifier is not None and not self.verifier(observation):
            key = (sampled, observation.get("image_signature"), observation.get("mac"))
            if key in self.forgeries:
                return None
            self.forgeries.append(key)
            return "observation_unauthenticated", {
                "sample_t_ms": sampled, "seen_at_ms": now,
                "claimed_sender": observation.get("actor"),
                "image_signature": observation.get("image_signature"),
                "has_mac": isinstance(observation.get("mac"), str),
            }
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
