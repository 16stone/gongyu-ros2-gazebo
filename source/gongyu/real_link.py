"""Measured inter-process link (phase110, opt-in).

Why this exists
---------------
Every registered card drives ``gongyu.communication.Network`` with a *declared*
delay and, in the stressed conditions, a *declared* jitter/loss rate.  The
report therefore had to say that the communication model was injected.  This
module measures a real OS-level link and replays that measurement through the
same Network contract.

What is measured
----------------
Two separate OS processes exchange UDP datagrams over loopback.  Round-trip
times come from ``time.monotonic_ns`` on the sending side; drops are real
kernel/socket timeouts, not a configured probability.  The samples are frozen
into ``MeasuredLinkProfile`` so an experiment can be replayed bit-for-bit
without re-running the probe.

What is NOT claimed
-------------------
Loopback UDP is not a radio and not a ROS 2 DDS network.  It does measure real
scheduling, buffering and syscall latency between independent processes, which
is exactly what the injected model lacked.  Because one simulated millisecond
is not one real millisecond, the profile maps the *shape* (quantile ratios) of
the measured distribution onto the card's nominal delay, in the same ratio
calibration used by ``验证/dds_channel_calibration.py``.  Absolute simulated
milliseconds remain a model quantity and are labelled as such.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import socket
import time

from .communication import Network


def _echo_server(port_queue, stop_port, packets):
    """Child process: bind its own socket, echo every datagram, report port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', 0))
    port_queue.put(sock.getsockname()[1])
    sock.settimeout(0.2)
    received = 0
    while True:
        try:
            if not stop_port.empty():
                break
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            continue
        received += 1
        sock.sendto(data, addr)
    sock.close()
    packets.put(received)


def measure_udp_rtt(n=1200, gap_s=0.001, timeout_s=0.5, seed=0):
    """Real two-process UDP round-trip measurement. Returns a profile dict."""
    if n <= 0:
        raise ValueError('n must be positive')
    ctx = mp.get_context('spawn')
    port_queue, packets = ctx.Queue(), ctx.Queue()
    stop = ctx.Queue()
    proc = ctx.Process(target=_echo_server, args=(port_queue, stop, packets))
    proc.start()
    try:
        server_port = port_queue.get(timeout=10)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 0))
        sock.settimeout(timeout_s)
        addr = ('127.0.0.1', server_port)
        rows = []
        for seq in range(n):
            payload = f'{seed}|{seq}|{time.monotonic_ns()}'.encode('ascii')
            sent = time.perf_counter_ns()
            sock.sendto(payload, addr)
            try:
                data, _ = sock.recvfrom(2048)
                rtt_ms = (time.perf_counter_ns() - sent) / 1e6
                rows.append(dict(seq=seq, rtt_ms=round(rtt_ms, 6), dropped=False,
                                 echoed=data == payload))
            except socket.timeout:
                rows.append(dict(seq=seq, rtt_ms=None, dropped=True, echoed=False))
            end = time.perf_counter() + gap_s
            while time.perf_counter() < end:
                pass
        sock.close()
    finally:
        stop.put(1)
        proc.join(timeout=10)
        if proc.is_alive():
            proc.terminate()
        packets_received = packets.get(timeout=5) if not packets.empty() else None
    observed = sorted(r['rtt_ms'] for r in rows if not r['dropped'] and r['rtt_ms'] is not None)
    echo_ok = sum(1 for r in rows if r['echoed'])
    return dict(transport='loopback UDP, two OS processes, real kernel round trip',
                samples=n, observed=len(observed),
                dropped=sum(1 for r in rows if r['dropped']),
                echoed_intact=echo_ok,
                server_received=packets_received,
                rtt_ms=dict(min=round(observed[0], 6) if observed else None,
                            p50=round(observed[len(observed) // 2], 6) if observed else None,
                            p95=round(observed[int(len(observed) * .95)], 6) if observed else None,
                            p99=round(observed[int(len(observed) * .99)], 6) if observed else None,
                            max=round(observed[-1], 6) if observed else None,
                            mean=round(sum(observed) / len(observed), 6) if observed else None),
                rows=rows,
                boundary='real process scheduling and socket latency; not radio, not DDS, not hardware')


def quantile(values, q):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * q))]


class MeasuredLinkProfile:
    """Frozen measurement, replayable by message id without re-running the probe."""

    def __init__(self, measurement, nominal_delay_ms, jitter_ratio_cap=0.25, seed=0):
        self.measurement = measurement
        self.nominal_delay_ms = int(nominal_delay_ms)
        self.seed = int(seed)
        values = [r['rtt_ms'] for r in measurement['rows']
                  if not r['dropped'] and r['rtt_ms'] is not None]
        if not values:
            raise ValueError('no observed round trips in measurement')
        p50 = quantile(values, .50)
        p99 = quantile(values, .99)
        # Ratio calibration: keep the *shape* of the measured tail relative to
        # its median, then express it as a fraction of the card's nominal delay.
        ratio = min(float(jitter_ratio_cap), max(0.0, (p99 - p50) / max(p50, 1e-6) / 10.0))
        self.jitter_ms = int(round(self.nominal_delay_ms * ratio))
        self.measured_drop_rate = measurement['dropped'] / measurement['samples']
        self.digest = hashlib.sha256(json.dumps(
            [r['rtt_ms'] for r in measurement['rows']], sort_keys=True).encode()).hexdigest()

    def _index(self, message_id):
        h = hashlib.sha256(f'{self.seed}|{message_id}'.encode('utf-8')).digest()
        return int.from_bytes(h[:8], 'big') % len(self.measurement['rows'])

    def offset_ms(self, message_id):
        """Measured-tail-shaped offset for one message, in simulated ms."""
        if not self.jitter_ms:
            return 0
        row = self.measurement['rows'][self._index(message_id)]
        if row['rtt_ms'] is None:
            return 0
        values = [r['rtt_ms'] for r in self.measurement['rows'] if r['rtt_ms'] is not None]
        p50 = quantile(values, .50)
        scaled = (row['rtt_ms'] - p50) / max(p50, 1e-6)
        return max(-self.jitter_ms, min(self.jitter_ms, int(round(self.jitter_ms * scaled))))

    def dropped(self, message_id):
        """Real drop events from the probe, replayed by a stable message hash."""
        if not self.measured_drop_rate:
            return False
        return self.measurement['rows'][self._index(message_id)]['dropped']

    def to_dict(self):
        return dict(transport=self.measurement['transport'],
                    samples=self.measurement['samples'],
                    observed=self.measurement['observed'],
                    dropped=self.measurement['dropped'],
                    rtt_ms=self.measurement['rtt_ms'],
                    nominal_delay_ms=self.nominal_delay_ms,
                    jitter_ms=self.jitter_ms,
                    measured_drop_rate=self.measured_drop_rate,
                    measurement_sha256=self.digest,
                    boundary=self.measurement['boundary'])


class MeasuredNetwork(Network):
    """Network whose impairment comes from a frozen real-link measurement."""

    def __init__(self, delay_ms, link, profile):
        super().__init__(delay_ms, link)
        self.profile = profile
        self.dropped = set()
        self.offsets = {}

    def send(self, sender, receiver, payload, now, message_id, contract_id=None,
             poses=None, delay_ms=None):
        message = super().send(sender, receiver, payload, now, message_id,
                               contract_id=contract_id, poses=poses,
                               delay_ms=delay_ms)
        if message is None:
            return None
        offset = self.profile.offset_ms(message_id)
        message.delivery_delay_ms = max(1, (message.delivery_delay_ms or self.delay) + offset)
        self.offsets[message_id] = offset
        if self.profile.dropped(message_id):
            self.dropped.add(message_id)
        return message

    def advance(self, now, poses):
        kept = []
        for message in super().advance(now, poses):
            if message.message_id in self.dropped:
                self.delivered.discard(message.message_id)
                self.failures.append((now, message.message_id, 'measured_link_drop'))
            else:
                kept.append(message)
        return kept
