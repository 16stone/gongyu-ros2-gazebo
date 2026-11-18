from dataclasses import dataclass, field


@dataclass(frozen=True)
class Report:
    source_id: str
    subject_id: str
    sampled_at: int
    valid_for_ms: int
    quality: float
    observation_region: str


@dataclass
class Message:
    sender: str
    receiver: str
    payload: object
    queued_at: int
    message_id: str
    sent_at: int | None = None
    arrived_at: int | None = None
    contract_id: str | None = None
    delivery_delay_ms: int | None = None


@dataclass(frozen=True)
class LocalView:
    agent_id: str
    now_ms: int
    node: str
    reports: tuple = ()
    inbox: tuple = ()
    own_tasks: tuple = ()
    public_map: dict = field(default_factory=dict)
    teammate_status: dict = field(default_factory=dict)
    reservations: tuple = ()
    inventory: str | None = None
    inspection_reports: tuple = ()


@dataclass(frozen=True)
class Action:
    kind: str
    target: str = ''


@dataclass
class Plan:
    actions: list = field(default_factory=list)


@dataclass(frozen=True)
class Diagnosis:
    status: str
    reason: str
    report_margin_ms: int | None = None


@dataclass
class Decision:
    chosen: str
    candidates: list
    elapsed_ms: float


@dataclass
class Event:
    run_id: str
    event_id: str
    t_ms: int
    actor: str
    kind: str
    payload: dict
    task_id: str | None = None
    contract_id: str | None = None
    caused_by: str | None = None
