"""A trainable single-agent decision layer, exposed as policy P4.

The analytic policies rank every candidate with a forecast the designer wrote down, so nothing
in them changes with experience. P4 keeps the hard checks -- which candidates are physically
lawful is still decided by the forecast -- and replaces only the *preference* with experience:
one UCB1 arm set per observable condition, updated with the reward the episode actually
earned. The estimates live between episodes and not inside a mission, which makes the learning
curve the thing being measured rather than a property of one lucky run.

Deliberate limits, stated so the curve is not over-read: the credit is episodic (every decision
an episode made is credited with the reward that episode earned, because the mission does not
attribute a single delivery to a single early choice), and the condition key is the published
scenario parameters, not the message history.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict

ACTIVE = None


def attach(bandit):
    """Install the learner the controllers will consult, or remove it again."""
    global ACTIVE
    ACTIVE = bandit
    return bandit


def context_of(view):
    """The condition the learner adapts to, from the map the agent is actually given."""
    m = view.public_map
    return (int(m['tau_ms']), int(m['service_ms']), int(m['channel_gap_ms']),
            int(m['message_delay_ms']), 'impaired' if m.get('channel_impairment') else 'clean')


class Bandit:
    """UCB1 over the lawful candidates, one arm set per observable condition."""

    def __init__(self, seed=0, exploration=2.0):
        self.rng = random.Random(seed)
        self.exploration = float(exploration)
        self.pulls = defaultdict(int)
        self.reward_sum = defaultdict(float)
        self.condition_pulls = defaultdict(int)
        self.pending = []
        self.episodes = 0

    def bound(self, condition, arm):
        n = self.pulls[(condition, arm)]
        if n == 0:
            return math.inf
        mean = self.reward_sum[(condition, arm)] / n
        return mean + math.sqrt(self.exploration * math.log(self.condition_pulls[condition]) / n)

    def choose(self, condition, lawful_arms):
        if not lawful_arms:
            raise ValueError('a learner with no lawful arm has nothing to learn from')
        self.condition_pulls[condition] += 1
        arms = sorted(lawful_arms)
        untried = [a for a in arms if self.pulls[(condition, a)] == 0]
        arm = (self.rng.choice(untried) if untried
               else max(arms, key=lambda a: (self.bound(condition, a), a)))
        self.pending.append((condition, arm))
        return arm

    def credit(self, reward):
        """Give every decision of the finished episode the reward that episode earned."""
        for condition, arm in self.pending:
            self.pulls[(condition, arm)] += 1
            self.reward_sum[(condition, arm)] += reward
        self.pending = []
        self.episodes += 1
        return reward

    def mean_reward(self, condition, arm):
        n = self.pulls[(condition, arm)]
        return None if n == 0 else self.reward_sum[(condition, arm)] / n

    def stats(self):
        return {'conditions': len(self.condition_pulls),
                'pulls': sum(self.pulls.values()),
                'distinct_arms_used': len({arm for arm in self.pulls}),
                'episodes': self.episodes}
