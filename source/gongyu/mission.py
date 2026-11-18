def report_valid(report,subject_id,now):
    return bool(report and report.subject_id==subject_id and report.quality>=1
                and 0<=now-report.sampled_at<=report.valid_for_ms)


class Mission:
    def __init__(self, cargo_subjects):
        self.subjects = cargo_subjects
        self.reports = {}
        self.claimed = {}
        self.inventory = {}
        self.loading = {}
        self.delivered = []

    def receive(self, actor, report):
        key = actor, report.subject_id
        if key not in self.reports or report.sampled_at >= self.reports[key].sampled_at:
            self.reports[key] = report

    def can_load(self, actor, cargo, now, node, can_transport=True):
        r = self.reports.get((actor, self.subjects[cargo]))
        return bool(can_transport and node == 'L' and actor not in self.inventory
                    and actor not in self.loading and cargo not in self.claimed
                    and report_valid(r,self.subjects[cargo],now))

    def start_load(self, actor, cargo, now, node, can_transport=True):
        if not self.can_load(actor, cargo, now, node, can_transport):
            raise ValueError('invalid load: position, capability, cargo or report')
        self.claimed[cargo] = actor
        self.loading[actor] = cargo

    def finish_load(self, actor, cargo):
        if self.loading.get(actor) != cargo or actor in self.inventory:
            raise ValueError('invalid load completion')
        del self.loading[actor]
        self.inventory[actor] = cargo

    def deliver(self, actor, node):
        if node != 'D' or actor not in self.inventory:
            return False
        self.delivered.append(self.inventory.pop(actor))
        return True


class Channel:
    def __init__(self, gap_ms):
        self.gap = gap_ms
        self.occupant = None
        self.clear_at = -gap_ms

    def enter(self, actor, now):
        if self.occupant is not None or now < self.clear_at+self.gap:
            return False
        self.occupant = actor
        return True

    def leave(self, actor, now):
        if self.occupant != actor:
            raise ValueError('channel exit without ownership')
        self.occupant = None
        self.clear_at = now
