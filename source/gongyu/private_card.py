"""Separate the public scene configuration from each unit's private task sheet.

A scene card mixes two different kinds of information. Geometry, nodes, edges,
fleet composition, speeds and protocol timings are *configuration*: every unit
needs the same copy in order to reason about the same map. The ``tasks`` list
and the card-level ``*_deadline_ms`` fields are different -- they state another
unit's delivery deadline. Handing the whole card to every entity process lets a
red unit read the blue deadline without ever receiving a message, which is a
leak that no deployed radio would have.

``private_card`` is applied on the entity side only. The referee always keeps
the original card for validation and metrics, so redaction cannot change a
result; it only removes information a deployment would never deliver. Public
configuration is copied unchanged, which is why the ten registered-card event
streams are bit-for-bit identical before and after this split.
"""
import copy

#: fields that carry a unit's private timing constraint
PRIVATE_TASK_FIELDS = ('deadline_ms',)
#: card-level deadline keys belong to the team named in their prefix
_TEAM_PREFIX = {'blue': 'B', 'red': 'R'}


def _public_card_key(key, actor):
    """A team-named deadline is private; every other card key is configuration."""
    if 'deadline' not in key:
        return True
    for word, team in _TEAM_PREFIX.items():
        if key.startswith(word + '_'):
            return actor.startswith(team)
    return True


def private_card(card, actor, own_task_ids=()):
    """Return the brief for one actor: public configuration, own deadlines only.

    ``own_task_ids`` comes from the referee's authoritative assignment table,
    so the split cannot be tricked by guessing a task owner from its id. Tasks
    outside that set keep their id, team and kind (the published mission
    structure) but lose their deadline. Applying the function twice is safe.
    """
    brief = copy.deepcopy(card)
    own = set(own_task_ids)
    for task in brief.get('tasks', ()):
        if task.get('id') in own:
            continue
        for field in PRIVATE_TASK_FIELDS:
            task.pop(field, None)
    for key in [k for k in brief if not _public_card_key(k, actor)]:
        brief.pop(key, None)
    return brief


def visible_deadlines(card):
    """Deadlines still present in a brief; used by the isolation tests."""
    return {t['id']: t['deadline_ms'] for t in card.get('tasks', ())
            if 'deadline_ms' in t}


__all__ = ['private_card', 'visible_deadlines']
