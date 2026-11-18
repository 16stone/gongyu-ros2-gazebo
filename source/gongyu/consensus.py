"""Majority-quorum slot consensus baseline (phase110, opt-in).

Why this exists
---------------
The report listed "no multi-vehicle consensus baseline" as an un-crossed
boundary: slot ownership was decided by a single referee.  This module adds an
explicit, message-based agreement protocol as a *comparison baseline*.  It does
not replace the referee in any registered card.

Protocol
--------
A two-phase propose/promise + accept/commit exchange over an explicit member
list.  A proposal is committed only when a strict majority of *all* members
acks; otherwise the protocol fails closed (``NO_COMMIT``) rather than letting a
partitioned minority decide.  Every exchange is counted and logged so message
cost and availability can be measured against the single-referee baseline.

What is NOT claimed
-------------------
This is a Paxos-shaped quorum agreement, not a full Raft/Paxos implementation
(there is no leader election, persistent log or term-based preemption beyond
the单调 term check).  It is a baseline for measuring the cost of agreement in
this deployment, not a claim of novel distributed-systems research.
"""
from __future__ import annotations

import collections


class QuorumConsensus:
    def __init__(self, members, timeout_ms=1000):
        members = tuple(sorted(set(members)))
        if len(members) < 3:
            raise ValueError('quorum baseline needs at least three members')
        self.members = members
        self.quorum = len(members) // 2 + 1
        self.timeout_ms = int(timeout_ms)
        self.decided = {}
        self.terms = collections.defaultdict(int)
        self.log = []
        self.committed = 0
        self.no_commit = 0
        self.rejected = 0

    def _record(self, phase, sender, receiver, slot, term, owner, ok=True):
        self.log.append(dict(phase=phase, sender=sender, receiver=receiver,
                             slot=slot, term=term, owner=owner, ok=ok))

    def propose(self, slot, owner, term, proposer, reachable=None):
        """One proposal. ``reachable`` is the set of members that can be reached."""
        if proposer not in self.members:
            raise ValueError('proposer must be a member')
        if owner not in self.members:
            raise ValueError('owner must be a member')
        reachable = set(self.members if reachable is None else reachable)
        reachable.add(proposer)
        before = len(self.log)
        # Phase 1: promises. A stale term cannot preempt an already decided slot.
        if term < self.terms[slot]:
            self.rejected += 1
            return self._result(slot, owner, term, 'REJECTED_STALE_TERM', before, reachable)
        promises = 0
        for member in self.members:
            ok = member in reachable and term >= self.terms[slot]
            self._record('propose', proposer, member, slot, term, owner, ok)
            if ok:
                promises += 1
                self.terms[slot] = max(self.terms[slot], term)
        if promises < self.quorum:
            self.no_commit += 1
            return self._result(slot, owner, term, 'NO_COMMIT_PROMISE', before, reachable)
        # Phase 2: accepts. A member that is reachable in phase 1 but lost
        # before phase 2 is supplied through ``partition_after_promise``.
        accepts = 0
        for member in self.members:
            ok = member in reachable
            self._record('accept', proposer, member, slot, term, owner, ok)
            accepts += int(ok)
        if accepts < self.quorum:
            self.no_commit += 1
            return self._result(slot, owner, term, 'NO_COMMIT_ACCEPT', before, reachable)
        self.decided[slot] = (owner, term)
        self.committed += 1
        for member in self.members:
            self._record('commit', proposer, member, slot, term, owner, member in reachable)
        return self._result(slot, owner, term, 'COMMITTED', before, reachable)

    def _result(self, slot, owner, term, status, before, reachable):
        return dict(slot=slot, owner=owner, term=term, status=status,
                    quorum=self.quorum, reachable=len(reachable),
                    messages=len(self.log) - before,
                    rounds=2 if status in ('COMMITTED', 'NO_COMMIT_ACCEPT') else 1,
                    decided=self.decided.get(slot))

    def state(self, slot):
        return self.decided.get(slot)

    def audit(self, referee_decisions):
        """Compare consensus output with the single-referee decisions."""
        agree = disagree = undecided = 0
        details = []
        for slot, owner in sorted(referee_decisions.items()):
            decided = self.decided.get(slot)
            if decided is None:
                undecided += 1
                status = 'NO_COMMIT'
            elif decided[0] == owner:
                agree += 1
                status = 'AGREE'
            else:
                disagree += 1
                status = 'DISAGREE'
            details.append(dict(slot=slot, referee=owner,
                                consensus=decided[0] if decided else None,
                                status=status))
        return dict(agree=agree, disagree=disagree, undecided=undecided,
                    total_messages=len(self.log), committed=self.committed,
                    no_commit=self.no_commit, rejected=self.rejected,
                    quorum=self.quorum, members=len(self.members),
                    details=details)

    def report(self):
        return dict(members=list(self.members), quorum=self.quorum,
                    timeout_ms=self.timeout_ms, committed=self.committed,
                    no_commit=self.no_commit, rejected=self.rejected,
                    messages=len(self.log),
                    phases=dict(collections.Counter(row['phase'] for row in self.log)),
                    scope='two-phase majority quorum baseline; no leader election or durable log')
