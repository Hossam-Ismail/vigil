"""Shared data shapes: the compiled watch spec and API payloads."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

WatchKind = Literal["state", "presence", "count"]
Trigger = Literal["rising", "sustained", "per_object"]
Severity = Literal["info", "warning", "critical"]
CountOp = Literal[">=", ">", "<=", "<", "=="]

Point = tuple[float, float]
Crossing = Literal["none", "any", "down", "up", "left", "right"]
ActionType = Literal["imessage", "hubspot", "webhook", "slack", "ntfy"]
MetricKind = Literal["count", "crossings", "occupancy"]


class Action(BaseModel):
    """Something Vigil does when a watch fires (after the double-check).

    imessage: text the snapshot to `target` (phone or Apple ID email) through the Photon iMessage bridge;
              replies like "yes"/"no" become training labels.
    hubspot:  create a CRM record; `object` is ticket | task | note.
    webhook / slack / ntfy: POST to `target` (URL, Slack webhook URL, or ntfy topic).
    An empty `target` falls back to the default configured in Settings.
    """

    type: ActionType
    target: str = ""
    object: str = ""
    note: str = ""


class Metric(BaseModel):
    """A number a watch keeps over time, shown on the Metrics page and in the watch's chart.

    count:     how many target objects are in the zone right now (a gauge: average and peak per period)
    crossings: how many tracked objects crossed the line (a counter: total per period, e.g. walk-ins)
    occupancy: share of the time the watch's answer is YES (e.g. % of the shift the staging area sat empty)
    """

    kind: MetricKind
    name: str  # what the number is, as the user would say it ("People waiting to pay")
    unit: str = ""  # "people", "walk-ins", "%"


class Zone(BaseModel):
    """A polygon in normalized image coordinates (0..1)."""

    points: list[Point]

    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (max(0.0, min(xs)), max(0.0, min(ys)), min(1.0, max(xs)), min(1.0, max(ys)))

    @classmethod
    def from_box(cls, x1: float, y1: float, x2: float, y2: float) -> "Zone":
        return cls(points=[(x1, y1), (x2, y1), (x2, y2), (x1, y2)])


class WatchSpec(BaseModel):
    """What a natural-language request compiles into.

    state:    classify a region of the frame every few seconds ("is the bin empty?")
    presence: detect target objects inside a zone ("a person is at the front door")
    count:    compare the number of target objects in a zone to a threshold ("fewer than 3 pallets")
    """

    name: str
    kind: WatchKind
    summary: str = ""
    question: str  # yes/no question about the frame or region, phrased so "yes" means alert-worthy
    positive_label: str  # short description of what "yes" looks like
    negative_label: str  # short description of what "no" looks like
    targets: list[str] = Field(default_factory=list)  # detector vocabulary for presence/count
    target_question: str = ""  # optional per-object yes/no check ("is this person wearing a hard hat?")
    locate: str = ""  # phrase used to find the region of interest ("the blue bin on the top shelf")
    locate_noun: str = ""  # short detector query for candidate regions ("blue bin")
    zone: Zone | None = None
    # presence only: a tripwire. When set, the watch fires when a tracked object crosses the line moving
    # in `crossing` direction (image space: "down" = toward the bottom of the frame).
    line: list[Point] | None = None
    crossing: Crossing = "none"
    count_op: CountOp = ">="
    count_value: int = 1
    min_duration_s: float = 2.0
    cooldown_s: float = 300.0
    trigger: Trigger = "rising"
    verify_with_vlm: bool = True
    severity: Severity = "warning"
    alert_message: str = ""
    check_interval_s: float = 1.0
    clarifications: list[str] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    metric: Metric | None = None  # keep a number over time instead of (or as well as) a yes/no alert
    alerts: bool = True  # False = a metric-only watch: it measures and charts, it never alerts
    library: dict | None = None  # a prebuilt model from the library: {"id": ..., "yes": [classes that mean YES]}


class CameraIn(BaseModel):
    name: str
    kind: Literal["rtsp", "http", "file", "webcam", "browser", "demo"]
    url: str = ""
    enabled: bool = True


class CameraPatch(BaseModel):
    name: str | None = None
    url: str | None = None
    enabled: bool | None = None


class WatchDraftIn(BaseModel):
    camera_id: int
    prompt: str


class WatchPatch(BaseModel):
    name: str | None = None
    spec: WatchSpec | None = None


class SampleLabelIn(BaseModel):
    label: int | None  # 1 = yes / alert-worthy, 0 = no, None = unlabeled


class FeedbackIn(BaseModel):
    feedback: Literal["correct", "false_alarm", "missed"] | None


class NotifyChannel(BaseModel):
    id: str
    type: Literal["webhook", "ntfy", "slack", "desktop"]
    target: str = ""  # url, ntfy topic, slack webhook url
    enabled: bool = True
    min_severity: Severity = "info"


class SettingsIn(BaseModel):
    channels: list[NotifyChannel] | None = None
    brain: str | None = None
    integrations: dict | None = None  # imessage_to, imessage_bridge, hubspot_token, public_url
    privacy: dict | None = None  # private_mode, blur_faces, keep_history_days, keep_events_days
