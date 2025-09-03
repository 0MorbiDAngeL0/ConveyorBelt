import time, random
from dataclasses import dataclass
from typing import Optional, List, Tuple
from enum import Enum, auto

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

@dataclass
class TON:
    pt: float
    _start: Optional[float] = None
    q: bool = False
    et: float = 0.0
    def update(self, en: bool, tnow: float):
        if en:
            if self._start is None:
                self._start = tnow
                self.et = 0.0
                self.q = False
            else:
                self.et = tnow - self._start
                self.q = self.et >= self.pt
        else:
            self._start = None
            self.et = 0.0
            self.q = False

@dataclass
class Edge:
    prev: bool = False
    def rising(self, now: bool) -> bool:
        r = (not self.prev) and now
        self.prev = now
        return r

@dataclass
class Hook:
    id: int
    pos: float
    speed: float
    load_id: Optional[int] = None

class ConveyorSim:
    def __init__(self, length=100.0, station_pos=(0, 25, 50, 75), zone=1.2, depot_pos=90.0):
        self.L = length
        self.station_pos = station_pos
        self.depot_pos = depot_pos
        self.zone = zone
        self.hooks: List[Hook] = []
        self.st_present: List[bool] = [False]*len(station_pos)
        self.st_hook_id: List[Optional[int]] = [None]*len(station_pos)
        self.depot_present: bool = False
        self.depot_hook_id: Optional[int] = None
    def add_hooks(self, count=8, base_speed=6.0, jitter=1.0):
        for i in range(count):
            self.hooks.append(Hook(
                id=i+1,
                pos=(i*(self.L/count))%self.L,
                speed=base_speed+random.uniform(-jitter, jitter)
            ))
    def _near(self, x, s) -> bool:
        d = min((x - s) % self.L, (s - x) % self.L)
        return d <= self.zone
    def step(self, dt: float):
        for h in self.hooks:
            h.pos = (h.pos + h.speed*dt) % self.L
        for i, s in enumerate(self.station_pos):
            nh = sorted(self.hooks, key=lambda h: min((h.pos - s) % self.L, (s - h.pos) % self.L))
            if nh and self._near(nh[0].pos, s):
                self.st_present[i] = True
                self.st_hook_id[i] = nh[0].id
            else:
                self.st_present[i] = False
                self.st_hook_id[i] = None
        nh = sorted(self.hooks, key=lambda h: min((h.pos - self.depot_pos) % self.L, (self.depot_pos - h.pos) % self.L))
        if nh and self._near(nh[0].pos, self.depot_pos):
            self.depot_present = True
            self.depot_hook_id = nh[0].id
        else:
            self.depot_present = False
            self.depot_hook_id = None

class SwapperHW:
    def __init__(self, move_time=0.7):
        self.ready = True
        self.busy = False
        self.complete = False
        self._ton = TON(move_time)
        self._latched_complete = 0
    def step(self, cmd: bool, tnow: float):
        if cmd and self.ready and not self.busy:
            self.ready = False
            self.busy = True
            self._ton.update(True, tnow)
        if self.busy:
            self._ton.update(True, tnow)
            if self._ton.q:
                self.busy = False
                self.complete = True
                self._latched_complete = 1
                self._ton.update(False, tnow)
        else:
            if self._latched_complete > 0:
                self._latched_complete -= 1
            else:
                self.complete = False
                self.ready = True

job_seq = 0

@dataclass
class Job:
    id: int
    station: int
    hook_id: int
    created_at: float
    laps: int = 0

class LifoScheduler:
    def __init__(self, max_laps_for_old: int = 2):
        self.jobs: List[Job] = []
        self.max_laps_for_old = max_laps_for_old
    def add(self, j: Job):
        self.jobs.append(j)
    def on_hook_passed_depot(self, hook_id: int):
        for j in self.jobs:
            if j.hook_id == hook_id:
                j.laps += 1
    def pick_next_job(self, depot_present_hook: Optional[int]) -> Optional[Job]:
        if not self.jobs:
            return None
        aged = [j for j in self.jobs if j.laps >= self.max_laps_for_old]
        if aged:
            return sorted(aged, key=lambda j: j.created_at)[0]
        newest = sorted(self.jobs, key=lambda j: j.created_at, reverse=True)
        return newest[0]
    def remove(self, job_id: int):
        self.jobs = [j for j in self.jobs if j.id != job_id]

class SState(Enum):
    IDLE = auto()
    LOADING = auto()
    DONE = auto()

@dataclass
class StationInputs:
    hook_present: bool
    hook_id: Optional[int]
    request_load: bool
    reset: bool = False

@dataclass
class StationOutputs:
    cmd: bool = False
    busy: bool = False
    done_pulse: bool = False

class StationFSM:
    def __init__(self, name: str, hw: SwapperHW, load_time=0.5):
        self.name = name
        self.hw = hw
        self.state = SState.IDLE
        self.out = StationOutputs()
        self._ton = TON(load_time)
        self._armed = False
    def arm(self):
        self._armed = True
    def scan(self, i: StationInputs, tnow: float) -> StationOutputs:
        o = self.out
        o.done_pulse = False
        if i.reset:
            self.state = SState.IDLE
            self._armed = False
        if self.state == SState.IDLE:
            o.cmd = False
            o.busy = False
            if i.request_load:
                self._armed = True
            if self._armed and i.hook_present and i.hook_id is not None and self.hw.ready:
                o.cmd = True
                o.busy = True
                self._ton.update(True, tnow)
                self.state = SState.LOADING
        elif self.state == SState.LOADING:
            self._ton.update(True, tnow)
            self.hw.step(o.cmd, tnow)
            if self.hw.complete or self._ton.q:
                o.cmd = False
                o.busy = False
                o.done_pulse = True
                self._armed = False
                self._ton.update(False, tnow)
                self.state = SState.DONE
        elif self.state == SState.DONE:
            if not i.hook_present:
                self.state = SState.IDLE
        return o

class DState(Enum):
    IDLE = auto()
    WAIT_TARGET = auto()
    TRANSFER = auto()

@dataclass
class DepotInputs:
    hook_present: bool
    hook_id: Optional[int]
    target_hook_id: Optional[int]
    hw_ready: bool
    hw_complete: bool

@dataclass
class DepotOutputs:
    cmd: bool = False
    busy: bool = False
    active_target: Optional[int] = None

class DepotFSM:
    def __init__(self, hw: SwapperHW, tmax=3.0):
        self.hw = hw
        self.state = DState.IDLE
        self.out = DepotOutputs()
        self._t = TON(tmax)
    def scan(self, i: DepotInputs, tnow: float) -> DepotOutputs:
        o = self.out
        if self.state == DState.IDLE:
            o.cmd = False; o.busy = False; o.active_target = i.target_hook_id
            if i.target_hook_id is not None:
                self.state = DState.WAIT_TARGET
        elif self.state == DState.WAIT_TARGET:
            o.active_target = i.target_hook_id
            if i.target_hook_id is None:
                self.state = DState.IDLE
            elif i.hook_present and (i.hook_id == i.target_hook_id) and i.hw_ready:
                o.cmd = True; o.busy = True
                self._t.update(True, tnow)
                self.state = DState.TRANSFER
        elif self.state == DState.TRANSFER:
            self.hw.step(o.cmd, tnow)
            self._t.update(True, tnow)
            if i.hw_complete or self._t.q:
                o.cmd = False; o.busy = False
                self._t.update(False, tnow)
                self.state = DState.IDLE
        return o

class OPCUAAdapter:
    def __init__(self, url: str, node_map: dict):
        self.url = url
        self.node_map = node_map
        self.client = None
    async def connect(self):
        from asyncua import Client
        self.client = Client(self.url)
        await self.client.connect()
    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
    async def read_bool(self, key: str) -> bool:
        from asyncua import ua
        node = self.client.get_node(self.node_map[key])
        return bool(await node.read_value())
    async def write_bool(self, key: str, value: bool):
        from asyncua import ua
        node = self.client.get_node(self.node_map[key])
        dv = ua.DataValue(ua.Variant(bool(value), ua.VariantType.Boolean))
        await node.write_value(dv)

class ConveyorLine:
    def __init__(self, length=120.0, zone=1.5):
        self.L = length
        self.zone = zone
        self.hooks: List[Hook] = []
    def add_hooks(self, count=16, base_speed=5.5, jitter=0.5):
        for i in range(count):
            self.hooks.append(Hook(
                id=i+1,
                pos=(i*(self.L/count))%self.L,
                speed=base_speed+random.uniform(-jitter, jitter)
            ))
    def step(self, dt: float):
        for h in self.hooks:
            h.pos = (h.pos + h.speed*dt) % self.L
    def nearest_hook_info(self, at_pos: float) -> Tuple[bool, Optional[int]]:
        if not self.hooks:
            return False, None
        def ring_dist(a, b):
            return min((a-b) % self.L, (b-a) % self.L)
        h = min(self.hooks, key=lambda k: ring_dist(k.pos, at_pos))
        near = ring_dist(h.pos, at_pos) <= self.zone
        return near, h.id if near else None
    def assign_job_to_free_hook_near(self, at_pos: float, job_id: int) -> Optional[int]:
        if not self.hooks:
            return None
        def ring_dist(a, b):
            return min((a-b) % self.L, (b-a) % self.L)
        free = [h for h in self.hooks if h.load_id is None]
        if not free:
            return None
        h = min(free, key=lambda k: ring_dist(k.pos, at_pos))
        if ring_dist(h.pos, at_pos) <= self.zone:
            h.load_id = job_id
            return h.id
        return None

class BufferLane:
    def __init__(self, lane_id: int, capacity: int = 30):
        self.id = lane_id
        self.capacity = capacity
        self.slots: List[int] = []
        self.release_at: dict[int, float] = {}
    def can_accept(self) -> bool:
        return len(self.slots) < self.capacity
    def put(self, job_id: int, now_sim: float, hold_seconds: float):
        self.slots.append(job_id)
        self.release_at[job_id] = now_sim + hold_seconds
    def tick_release(self, now_sim: float) -> List[int]:
        rel = [jid for jid in list(self.slots) if self.release_at.get(jid, 1e18) <= now_sim]
        for jid in rel:
            self.slots.remove(jid)
            self.release_at.pop(jid, None)
        return rel

class FeederFSM:
    class S(Enum):
        IDLE = auto()
        TRANSFER = auto()
    def __init__(self, hw: SwapperHW, pos: float):
        self.hw = hw
        self.pos = pos
        self.state = self.S.IDLE
        self.current_job: Optional[int] = None
        self._t = TON(0.6)
    def scan(self, next_job: Optional[int], line1: ConveyorLine, tnow: float) -> Tuple[bool, Optional[int]]:
        if self.state == self.S.IDLE:
            if next_job is not None and self.hw.ready:
                near, _ = line1.nearest_hook_info(self.pos)
                if near:
                    self.current_job = next_job
                    self._t.update(True, tnow)
                    self.state = self.S.TRANSFER
        elif self.state == self.S.TRANSFER:
            self.hw.step(True, tnow)
            self._t.update(True, tnow)
            if self.hw.complete:
                hid = line1.assign_job_to_free_hook_near(self.pos, self.current_job)
                self._t.update(False, tnow)
                self.state = self.S.IDLE
                cj = self.current_job
                self.current_job = None
                return True if hid is not None else False, hid
            elif self._t.q:
                self._t.update(False, tnow)
                self.state = self.S.IDLE
        return False, None

class SorterFSM:
    class S(Enum):
        IDLE = auto()
        TRANSFER = auto()
    def __init__(self, hw: SwapperHW, pos: float, hold_seconds: float, lanes: List[BufferLane]):
        self.hw = hw
        self.pos = pos
        self.hold_seconds = hold_seconds
        self.lanes = lanes
        self.state = self.S.IDLE
        self._t = TON(0.8)
        self.target_lane: Optional[int] = None
    def pick_lane(self) -> Optional[int]:
        free = [ln.id for ln in self.lanes if ln.can_accept()]
        return random.choice(free) if free else None
    def scan(self, line1: ConveyorLine, now_sim: float, tnow: float) -> Optional[Tuple[int,int]]:
        near, hid = line1.nearest_hook_info(self.pos)
        hook = None
        if hid is not None:
            hook = next(h for h in line1.hooks if h.id == hid)
        if self.state == self.S.IDLE:
            if near and hook and hook.load_id is not None and self.hw.ready:
                lnid = self.pick_lane()
                if lnid is not None:
                    self.target_lane = lnid
                    self._t.update(True, tnow)
                    self.state = self.S.TRANSFER
        elif self.state == self.S.TRANSFER:
            self.hw.step(True, tnow)
            self._t.update(True, tnow)
            if self.hw.complete:
                if hook and hook.load_id is not None and self.target_lane is not None:
                    jid = hook.load_id
                    hook.load_id = None
                    lane = next(ln for ln in self.lanes if ln.id == self.target_lane)
                    lane.put(jid, now_sim, self.hold_seconds)
                    tl = self.target_lane
                    self._t.update(False, tnow)
                    self.state = self.S.IDLE
                    self.target_lane = None
                    return jid, tl
                self._t.update(False, tnow)
                self.state = self.S.IDLE
            elif self._t.q:
                self._t.update(False, tnow)
                self.state = self.S.IDLE
        return None

def main():
    random.seed(42)
    station_pos = (0.0, 25.0, 50.0, 75.0)
    depot_pos   = 90.0
    sim = ConveyorSim(length=100.0, station_pos=station_pos, zone=1.2, depot_pos=depot_pos)
    sim.add_hooks(count=10, base_speed=6.0, jitter=0.7)
    st_hw = [SwapperHW(move_time=0.4+0.1*i) for i in range(4)]
    st_fsm = [StationFSM(f"S{i+1}", st_hw[i], load_time=0.3+0.05*i) for i in range(4)]
    dp_hw = SwapperHW(move_time=0.5)
    depot = DepotFSM(dp_hw, tmax=3.0)
    sched = LifoScheduler(max_laps_for_old=2)
    line1 = ConveyorLine(length=120.0, zone=1.5)
    line1.add_hooks(count=16, base_speed=5.5, jitter=0.5)
    LINE1_FEED_POS = 5.0
    LINE1_SORT_POS = 70.0
    feeder_hw = SwapperHW(move_time=0.45)
    feeder = FeederFSM(feeder_hw, pos=LINE1_FEED_POS)
    sorter_hw = SwapperHW(move_time=0.6)
    LANES = [BufferLane(lane_id=i+1, capacity=30) for i in range(42)]
    HOLD_12H = 12*3600
    sorter = SorterFSM(sorter_hw, pos=LINE1_SORT_POS, hold_seconds=HOLD_12H, lanes=LANES)
    waiting_to_line1: List[int] = []
    job_info = {}
    SIM_SPEEDUP = 3600
    scan = 0.02
    tprev = time.monotonic()
    sim_clock = 0.0
    global job_seq
    print("Tuşlar: 1/2/3/4=iş iste, q=çıkış")
    try:
        while True:
            tnow = time.monotonic()
            dt = tnow - tprev
            tprev = tnow
            sim_clock += dt*SIM_SPEEDUP
            if HAS_MSVCRT:
                while msvcrt.kbhit():
                    ch = msvcrt.getch().decode(errors='ignore').lower()
                    if ch == 'q':
                        raise KeyboardInterrupt
                    if ch in ('1','2','3','4'):
                        idx = int(ch)-1
                        st_fsm[idx].arm()
                        print(f"\n[REQ] S{idx+1}")
            sim.step(dt)
            line1.step(dt)
            for si in range(4):
                i = StationInputs(
                    hook_present = sim.st_present[si],
                    hook_id      = sim.st_hook_id[si],
                    request_load = False,
                    reset        = False
                )
                o = st_fsm[si].scan(i, tnow)
                st_hw[si].step(o.cmd, tnow)
                if o.done_pulse and sim.st_hook_id[si] is not None:
                    job_seq += 1
                    hid = sim.st_hook_id[si]
                    for h in sim.hooks:
                        if h.id == hid:
                            h.load_id = job_seq
                    j = Job(id=job_seq, station=si+1, hook_id=hid, created_at=tnow)
                    sched.add(j)
                    job_info[j.id] = {"state":"TO_DEPOT","line1_hook":None,"lane":None,"release_at":None}
                    print(f"\n[LOAD] S{si+1} -> Hook {hid} | Job#{j.id}")
            target_job = sched.pick_next_job(sim.depot_hook_id)
            target_hook = target_job.hook_id if target_job else None
            di = DepotInputs(
                hook_present = sim.depot_present,
                hook_id      = sim.depot_hook_id,
                target_hook_id = target_hook,
                hw_ready     = dp_hw.ready,
                hw_complete  = dp_hw.complete
            )
            do = depot.scan(di, tnow)
            dp_hw.step(do.cmd, tnow)
            if dp_hw.complete and target_job and sim.depot_hook_id == target_hook:
                print(f"\n[DEPOT] Job#{target_job.id} boşaltıldı")
                for h in sim.hooks:
                    if h.id == target_hook:
                        h.load_id = None
                sched.remove(target_job.id)
                waiting_to_line1.append(target_job.id)
                job_info[target_job.id]["state"] = "TO_LINE1"
            if sim.depot_present and sim.depot_hook_id is not None:
                current_hook = sim.depot_hook_id
                if (not target_job) or (current_hook != target_hook):
                    sched.on_hook_passed_depot(current_hook)
            next_job = waiting_to_line1[0] if waiting_to_line1 else None
            transferred, bound = feeder.scan(next_job, line1, tnow)
            if transferred and bound is not None and next_job is not None:
                waiting_to_line1.pop(0)
                job_info[next_job]["state"] = "ON_LINE1"
                job_info[next_job]["line1_hook"] = bound
                print(f"\n[FEED] Job#{next_job} Line1-Hook{bound}")
            res = sorter.scan(line1, sim_clock, tnow)
            if res:
                jid, ln = res
                job_info[jid]["state"] = "STORED"
                job_info[jid]["lane"] = ln
                job_info[jid]["release_at"] = sim_clock + HOLD_12H
                print(f"\n[SORT] Job#{jid} Lane#{ln}")
            for ln in LANES:
                rel = ln.tick_release(sim_clock)
                for j in rel:
                    print(f"\n[RELEASE] Lane#{ln.id} -> Job#{j}")
                    job_info.pop(j, None)
            if int(sim_clock) % 2 == 0:
                q = [j.id for j in sorted(sched.jobs, key=lambda x: x.created_at)]
                waiting = list(waiting_to_line1)
                storing = sum(len(ln.slots) for ln in LANES)
                free_lanes = sum(1 for ln in LANES if ln.can_accept())
                near_feed, hfid = line1.nearest_hook_info(LINE1_FEED_POS)
                near_sort, hsid = line1.nearest_hook_info(LINE1_SORT_POS)
                s = " | ".join(f"S{i+1}:P{int(sim.st_present[i])}" for i in range(4))
                print(f"{s} | Depot:P{int(sim.depot_present)} H:{sim.depot_hook_id} | Q:{q} | TgtHook:{target_hook} | W2L:{waiting} | Store:{storing} | Free:{free_lanes}/42 | FeedP{int(near_feed)}H{hfid} | SortP{int(near_sort)}H{hsid}", end="\r")
            rem = scan - (time.monotonic() - tnow)
            if rem > 0:
                time.sleep(rem)
    except KeyboardInterrupt:
        print("\nÇıkılıyor...")

if __name__ == "__main__":
    main()
