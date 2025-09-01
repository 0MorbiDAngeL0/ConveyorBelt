from __future__ import annotations
import time
from dataclasses import dataclass, field
from collections import deque
from typing import Deque, Dict, Iterable, List, Optional, Tuple

STATION_COUNT = 4
BELTS_COUNT = 42

STATION_POSITIONS = {1: 60.0, 2: 40.0, 3: 20.0, 4: 10.0}
CONVEYOR_SPEED = 1.0
LINE2_LENGTH = 30.0
UNLOAD_LINE_LENGTH = 15.0

SERPENTINE_ORDER: List[int] = [
     1,  2,  3,  4,  5,  6,
    12, 11, 10,  9,  8,  7,
    13, 14, 15, 16, 17, 18,
    24, 23, 22, 21, 20, 19,
    25, 26, 27, 28, 29, 30,
    36, 35, 34, 33, 32, 31,
    37, 38, 39, 40, 41, 42
]

UNLOAD_POLICY = "round_robin"  # "round_robin" | "balance"
BELT_PROCESS_TIME = 2
UNLOAD_CAPACITY = 999
LINE2_PULL_RATE = 999
DT = 1.0

@dataclass
class Item:
    id: int
    source_station: int
    t_arrival: int

@dataclass
class MovingItem:
    id: int
    source_station: int
    pos: float
    target_dist: float

@dataclass
class Belt:
    idx: int
    process_time: int
    current: Optional[Item] = None
    remaining: int = 0
    queue: Deque[Item] = field(default_factory=deque)
    def push(self, it: Item): self.queue.append(it)
    def tick(self) -> Optional[Item]:
        if self.current is None and self.queue:
            self.current = self.queue.popleft()
            self.remaining = self.process_time
        if self.current is not None:
            self.remaining -= 1
            if self.remaining <= 0:
                done = self.current
                self.current = None
                return done
        return None

@dataclass
class UnloadStation:
    name: str
    capacity_per_tick: int = UNLOAD_CAPACITY
    queue: Deque[Item] = field(default_factory=deque)
    unloaded_log: List[Tuple[int, int]] = field(default_factory=list)
    def push(self, it: Item): self.queue.append(it)
    def tick(self, t: int):
        processed = 0
        while self.queue and processed < self.capacity_per_tick:
            it = self.queue.popleft()
            self.unloaded_log.append((t, it.id))
            processed += 1

@dataclass
class Segment:
    length: float
    speed: float
    moving: List[MovingItem] = field(default_factory=list)
    def step(self, dt: float) -> List[MovingItem]:
        arrived = []
        for it in self.moving:
            it.pos += self.speed * dt
        for it in list(self.moving):
            if it.pos >= it.target_dist:
                arrived.append(it)
                self.moving.remove(it)
        return arrived

class ConveyorSystem:
    def __init__(self):
        self.belts: Dict[int, Belt] = {i: Belt(idx=i, process_time=BELT_PROCESS_TIME) for i in range(1, BELTS_COUNT + 1)}
        self.serpentine_order = SERPENTINE_ORDER
        self.swapper_queue: Deque[Item] = deque()
        self.unload1 = UnloadStation("Boşaltma 1")
        self.unload2 = UnloadStation("Boşaltma 2")
        self.segments_st: Dict[int, Segment] = {st: Segment(length=STATION_POSITIONS[st], speed=CONVEYOR_SPEED) for st in STATION_POSITIONS}
        self.line2 = Segment(length=LINE2_LENGTH, speed=CONVEYOR_SPEED)
        self.unload_seg1 = Segment(length=UNLOAD_LINE_LENGTH, speed=CONVEYOR_SPEED)
        self.unload_seg2 = Segment(length=UNLOAD_LINE_LENGTH, speed=CONVEYOR_SPEED)
        self._global_arrival_counter = 0
        self._rr_unload_toggle = 0
        self._item_id_seq = 1
        self.time = 0.0

    def add_items(self, produced_per_station: Iterable[int]):
        for station_idx, n in enumerate(produced_per_station, start=1):
            for _ in range(n):
                item_id = self._item_id_seq; self._item_id_seq += 1
                self.segments_st[station_idx].moving.append(MovingItem(item_id, station_idx, 0.0, self.segments_st[station_idx].length))

    def step_station_segments(self) -> List[Item]:
        arrived: List[Item] = []
        for seg in self.segments_st.values():
            a = seg.step(DT)
            for m in a:
                arrived.append(Item(m.id, m.source_station, int(self.time)))
        return arrived

    def dispatch_to_belts(self):
        belts_list = list(self.belts.values())
        while self.swapper_queue:
            it = self.swapper_queue.popleft()
            placed = False
            for belt in belts_list:
                if belt.current is None and not belt.queue:
                    belt.push(it); placed = True; break
            if not placed:
                belt_no = (self._global_arrival_counter % len(self.belts)) + 1
                self.belts[belt_no].push(it)
            self._global_arrival_counter += 1

    def belts_to_line2(self):
        pulled = 0
        new_on_line2: List[MovingItem] = []
        for belt_no in self.serpentine_order:
            if pulled >= LINE2_PULL_RATE: break
            finished = self.belts[belt_no].tick()
            if finished:
                new_on_line2.append(MovingItem(finished.id, finished.source_station, 0.0, self.line2.length))
                pulled += 1
        if new_on_line2:
            self.line2.moving.extend(new_on_line2)

    def line2_to_unload_segments(self):
        arrived = self.line2.step(DT)
        for m in arrived:
            if UNLOAD_POLICY == "balance":
                seg1_load = len(self.unload_seg1.moving) + len(self.unload1.queue)
                seg2_load = len(self.unload_seg2.moving) + len(self.unload2.queue)
                target = self.unload_seg1 if seg1_load <= seg2_load else self.unload_seg2
            else:
                target = self.unload_seg1 if (self._rr_unload_toggle % 2 == 0) else self.unload_seg2
                self._rr_unload_toggle += 1
            target.moving.append(MovingItem(m.id, m.source_station, 0.0, target.length))

    def unload_segments_to_stations(self):
        a1 = self.unload_seg1.step(DT)
        a2 = self.unload_seg2.step(DT)
        for m in a1: self.unload1.push(Item(m.id, m.source_station, int(self.time)))
        for m in a2: self.unload2.push(Item(m.id, m.source_station, int(self.time)))

    def tick_unloaders(self):
        self.unload1.tick(int(self.time)); self.unload2.tick(int(self.time))

    def tick(self, produced_per_station=(1,1,1,1)):
        self.time += DT
        self.add_items(produced_per_station)
        for it in self.step_station_segments(): self.swapper_queue.append(it)
        self.dispatch_to_belts()
        self.belts_to_line2()
        self.line2_to_unload_segments()
        self.unload_segments_to_stations()
        self.tick_unloaders()

    def snapshot(self):
        belts_load = {i: len(self.belts[i].queue) + (1 if self.belts[i].current else 0) for i in self.belts}
        inflight = sum(len(s.moving) for s in self.segments_st.values())
        return {
            "time": self.time,
            "inflight_st": inflight,
            "swapper_q": len(self.swapper_queue),
            "line2_mov": len(self.line2.moving),
            "u1_mov": len(self.unload_seg1.moving),
            "u2_mov": len(self.unload_seg2.moving),
            "u1_q": len(self.unload1.queue),
            "u2_q": len(self.unload2.queue),
            "u1": len(self.unload1.unloaded_log),
            "u2": len(self.unload2.unloaded_log),
        }

if __name__ == "__main__":
    system = ConveyorSystem()
    t = 0
    while True:
        system.tick((1,1,1,1))
        t += 1
        if t % 5 == 0:
            s = system.snapshot()
            print(f"[t={int(s['time'])}] inflight={s['inflight_st']} swapper={s['swapper_q']} "
                  f"line2={s['line2_mov']} U1mov={s['u1_mov']} U2mov={s['u2_mov']} "
                  f"U1q={s['u1_q']} U2q={s['u2_q']} U1={s['u1']} U2={s['u2']}")
        time.sleep(DT)
