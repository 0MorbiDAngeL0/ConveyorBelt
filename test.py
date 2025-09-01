from __future__ import annotations
import time, msvcrt
from dataclasses import dataclass, field
from collections import deque
from typing import Deque, Dict, Iterable, List, Optional, Tuple

STATION_COUNT = 4
BELTS_COUNT = 42

STATION_POSITIONS = {1: 60.0, 2: 40.0, 3: 20.0, 4: 10.0}
SPEED_COLLECT = 1.0
SPEED_DRAIN = 2.0

BELT_PROCESS_TIME_COLLECT_S = 10**9
BELT_PROCESS_TIME_DRAIN_S = 60.0

LINE2_LENGTH = 300.0
UNLOAD_LINE_LENGTH = 150.0

UNLOAD_POLICY = "round_robin"
UNLOAD_CAPACITY = 10**9

DT = 0.5
PRINT_EVERY = 2.0

DRAIN_MAX_SECONDS = 15 * 60

SERPENTINE_ORDER = [
     1,  2,  3,  4,  5,  6,
    12, 11, 10,  9,  8,  7,
    13, 14, 15, 16, 17, 18,
    24, 23, 22, 21, 20, 19,
    25, 26, 27, 28, 29, 30,
    36, 35, 34, 33, 32, 31,
    37, 38, 39, 40, 41, 42
]

@dataclass
class Item:
    id: int
    source_station: int
    born_t: float

@dataclass
class MovingItem:
    id: int
    source_station: int
    pos: float
    target: float

@dataclass
class Segment:
    length: float
    speed_fn: callable
    moving: List[MovingItem] = field(default_factory=list)
    def step(self, dt: float) -> List[MovingItem]:
        arr = []
        sp = self.speed_fn()
        for it in self.moving:
            it.pos += sp * dt
        for it in list(self.moving):
            if it.pos >= it.target:
                arr.append(it); self.moving.remove(it)
        return arr

@dataclass
class Belt:
    idx: int
    proc_time_fn: callable
    queue: Deque[Item] = field(default_factory=deque)
    cur: Optional[Tuple[Item, float]] = None
    def push(self, it: Item): self.queue.append(it)
    def step(self, dt: float) -> List[Item]:
        out = []
        if self.cur is None and self.queue:
            self.cur = (self.queue.popleft(), self.proc_time_fn())
        if self.cur is not None:
            item, rem = self.cur
            rem -= dt
            if rem <= 0:
                out.append(item); self.cur = None
            else:
                self.cur = (item, rem)
        return out

@dataclass
class UnloadStation:
    name: str
    cap_fn: callable
    q: Deque[Item] = field(default_factory=deque)
    log: List[Tuple[float, int]] = field(default_factory=list)
    def push(self, it: Item): self.q.append(it)
    def step(self, now: float):
        cap = self.cap_fn()
        taken = 0
        while self.q and taken < cap:
            it = self.q.popleft()
            self.log.append((now, it.id))
            taken += 1

class Conveyor:
    def __init__(self):
        self.mode = "COLLECT"
        self.mode_since = time.time()
        self.start_t = self.mode_since
        self.last_print = self.start_t
        self.time = 0.0
        self.next_id = 1
        self.rr = 0

        self.st_segments: Dict[int, Segment] = {
            s: Segment(STATION_POSITIONS[s], lambda m=self: SPEED_COLLECT if m.mode=="COLLECT" else SPEED_DRAIN)
            for s in STATION_COUNT*[1]
        }
        self.st_segments = {i+1: Segment(STATION_POSITIONS[i+1],
                             lambda m=self: SPEED_COLLECT if m.mode=="COLLECT" else SPEED_DRAIN)
                             for i in range(STATION_COUNT)}

        self.swapper_q: Deque[Item] = deque()

        self.belts: Dict[int, Belt] = {
            i: Belt(i, lambda m=self: BELT_PROCESS_TIME_COLLECT_S if m.mode=="COLLECT" else BELT_PROCESS_TIME_DRAIN_S)
            for i in range(1, BELTS_COUNT+1)
        }

        self.line2 = Segment(LINE2_LENGTH, lambda m=self: SPEED_COLLECT if m.mode=="COLLECT" else SPEED_DRAIN)
        self.unload1_seg = Segment(UNLOAD_LINE_LENGTH, lambda m=self: SPEED_COLLECT if m.mode=="COLLECT" else SPEED_DRAIN)
        self.unload2_seg = Segment(UNLOAD_LINE_LENGTH, lambda m=self: SPEED_COLLECT if m.mode=="COLLECT" else SPEED_DRAIN)

        self.unload1 = UnloadStation("U1", lambda: UNLOAD_CAPACITY)
        self.unload2 = UnloadStation("U2", lambda: UNLOAD_CAPACITY)

    def produce(self, rates_per_sec=(1,1,1,1)):
        for s, rps in enumerate(rates_per_sec, start=1):
            lam = rps * DT
            k = int(lam)
            if (lam - k) > 0:
                k += 1 if (time.time_ns() % 1_000_000_000)/1_000_000_000 < (lam - int(lam)) else 0
            for _ in range(k):
                self.st_segments[s].moving.append(MovingItem(self.next_id, s, 0.0, self.st_segments[s].length))
                self.next_id += 1

    def step_stations(self):
        for s in range(1, STATION_COUNT+1):
            arr = self.st_segments[s].step(DT)
            for m in arr:
                self.swapper_q.append(Item(m.id, m.source_station, self.time))

    def dispatch_to_belts(self):
        belts_list = [self.belts[i] for i in range(1, BELTS_COUNT+1)]
        while self.swapper_q:
            it = self.swapper_q.popleft()
            placed = False
            for b in belts_list:
                if (b.cur is None) and (not b.queue) and self.mode=="DRAIN":
                    b.push(it); placed = True; break
                if (b.cur is None) and (not b.queue) and self.mode=="COLLECT":
                    b.push(it); placed = True; break
            if not placed:
                b = self.belts[SERPENTINE_ORDER[self.rr % BELTS_COUNT]]
                b.push(it); self.rr += 1

    def step_belts(self) -> List[Item]:
        out = []
        for i in SERPENTINE_ORDER:
            out.extend(self.belts[i].step(DT))
        return out

    def belts_to_line2(self, items: List[Item]):
        if not items: return
        for it in items:
            self.line2.moving.append(MovingItem(it.id, it.source_station, 0.0, self.line2.length))

    def step_line2(self) -> List[MovingItem]:
        return self.line2.step(DT)

    def line2_to_unload_segs(self, arr: List[MovingItem]):
        for m in arr:
            if UNLOAD_POLICY == "balance":
                tgt = self.unload1_seg if (len(self.unload1_seg.moving) <= len(self.unload2_seg.moving)) else self.unload2_seg
            else:
                tgt = self.unload1_seg if (self.rr % 2 == 0) else self.unload2_seg
                self.rr += 1
            tgt.moving.append(MovingItem(m.id, m.source_station, 0.0, tgt.length))

    def step_unload_segs(self) -> Tuple[List[MovingItem], List[MovingItem]]:
        return self.unload1_seg.step(DT), self.unload2_seg.step(DT)

    def unload_push(self, a1: List[MovingItem], a2: List[MovingItem]):
        for m in a1: self.unload1.push(Item(m.id, m.source_station, self.time))
        for m in a2: self.unload2.push(Item(m.id, m.source_station, self.time))

    def unload_step(self):
        now = self.start_t + self.time
        self.unload1.step(now)
        self.unload2.step(now)

    def ensure_15min_deadline(self):
        if self.mode != "DRAIN": return
        elapsed = time.time() - self.mode_since
        if elapsed > DRAIN_MAX_SECONDS:
            pass

    def tick(self, rates=(1,1,1,1)):
        self.time += DT
        self.produce(rates)
        self.step_stations()
        self.dispatch_to_belts()
        out = self.step_belts()
        self.belts_to_line2(out)
        arr = self.step_line2()
        self.line2_to_unload_segs(arr)
        a1, a2 = self.step_unload_segs()
        self.unload_push(a1, a2)
        self.unload_step()
        self.ensure_15min_deadline()

    def snapshot(self):
        return {
            "mode": self.mode,
            "t": self.time,
            "inflight": sum(len(s.moving) for s in self.st_segments.values()),
            "swap_q": len(self.swapper_q),
            "belts_q": sum(len(b.queue) + (1 if b.cur else 0) for b in self.belts.values()),
            "line2": len(self.line2.moving),
            "u1mov": len(self.unload1_seg.moving),
            "u2mov": len(self.unload2_seg.moving),
            "u1q": len(self.unload1.q),
            "u2q": len(self.unload2.q),
            "u1": len(self.unload1.log),
            "u2": len(self.unload2.log)
        }

    def enter_drain(self):
        if self.mode == "DRAIN": return
        self.mode = "DRAIN"
        self.mode_since = time.time()

def main():
    sys = Conveyor()
    last_print = time.time()
    while True:
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ('q','Q'): break
            if ch in ('r','R'): sys.enter_drain()
        sys.tick(rates=(1,1,1,1))
        if time.time() - last_print >= PRINT_EVERY:
            s = sys.snapshot()
            print(f"[{s['mode']}] t={s['t']:.1f}s inflight={s['inflight']} swap={s['swap_q']} "
                  f"belts={s['belts_q']} line2={s['line2']} U1mov={s['u1mov']} U2mov={s['u2mov']} "
                  f"U1q={s['u1q']} U2q={s['u2q']} U1={s['u1']} U2={s['u2']}")
            last_print = time.time()
        time.sleep(DT)

if __name__ == "__main__":
    main()
