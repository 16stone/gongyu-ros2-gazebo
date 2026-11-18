import hashlib

from .model import Message


class Network:
    def __init__(self, delay_ms, link):
        if delay_ms <= 0:
            raise ValueError('message delay must be positive')
        self.delay = delay_ms
        self.link = link
        self.queue = []
        self.delivered = set()
        self.failures = []

    def send(self, sender, receiver, payload, now, message_id, contract_id=None, poses=None,delay_ms=None):
        if delay_ms is not None and (not isinstance(delay_ms,int) or delay_ms<=0):
            raise ValueError('per-message delay must be a positive integer')
        if message_id in self.delivered or any(m.message_id == message_id for m in self.queue):
            return
        m = Message(sender, receiver, payload, now, message_id, contract_id=contract_id,delivery_delay_ms=delay_ms)
        if poses is not None and poses.get(sender) is not None and poses.get(receiver) is not None and self.link(poses[sender],poses[receiver]):
            m.sent_at = now
        self.queue.append(m)
        return m

    def advance(self, now, poses):
        delivered, waiting = [], []
        for m in self.queue:
            connected = (poses.get(m.sender) is not None and poses.get(m.receiver) is not None
                         and self.link(poses[m.sender], poses[m.receiver]))
            if m.sent_at is None:
                if connected:
                    m.sent_at = now
                waiting.append(m)
            elif now >= m.sent_at + (m.delivery_delay_ms or self.delay):
                if connected:
                    m.arrived_at = now
                    self.delivered.add(m.message_id)
                    delivered.append(m)
                else:
                    self.failures.append((now, m.message_id, 'link_lost_at_arrival'))
            else:
                waiting.append(m)
        self.queue = waiting
        return delivered


class ImpairedNetwork(Network):
    """Fixed-delay link plus deterministic per-message jitter and random drop.

    Both draws come from a hash of the seed and the message id, so impairment is
    a property of the message rather than of the order in which the queue happens
    to be advanced. A dropped message leaves the delivered set, so a retransmission
    under a fresh id can still reach the receiver.
    """

    def __init__(self, delay_ms, link, jitter_ms=0, loss_rate=0.0, seed=0):
        super().__init__(delay_ms, link)
        if jitter_ms < 0 or jitter_ms >= delay_ms:
            raise ValueError('jitter must stay below the nominal message delay')
        if not 0 <= loss_rate < 1:
            raise ValueError('loss rate must lie in [0, 1)')
        self.jitter = jitter_ms
        self.loss_rate = loss_rate
        self.seed = seed
        self.offsets = {}
        self.planned_drops = set()
        self.dropped = set()

    def _unit(self, message_id, tag):
        digest = hashlib.sha256(f'{self.seed}|{tag}|{message_id}'.encode('utf-8')).digest()
        return int.from_bytes(digest[:8], 'big') / 2 ** 64

    def send(self, *args, **kwargs):
        message = super().send(*args, **kwargs)
        if message is None:
            return None
        if self.jitter:
            offset = int(round(self.jitter * (2 * self._unit(message.message_id, 'jitter') - 1)))
            message.delivery_delay_ms = max(1, (message.delivery_delay_ms or self.delay) + offset)
            self.offsets[message.message_id] = offset
        if self.loss_rate and self._unit(message.message_id, 'drop') < self.loss_rate:
            self.planned_drops.add(message.message_id)
        return message

    def advance(self, now, poses):
        kept = []
        for message in super().advance(now, poses):
            if message.message_id in self.planned_drops:
                self.delivered.discard(message.message_id)
                self.dropped.add(message.message_id)
                self.failures.append((now, message.message_id, 'random_drop'))
            else:
                kept.append(message)
        return kept

    def failure_reasons(self):
        reasons = {}
        for _, _, reason in self.failures:
            reasons[reason] = reasons.get(reason, 0) + 1
        return reasons
