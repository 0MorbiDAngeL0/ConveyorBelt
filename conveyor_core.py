from __future__ import annotations
import time, random
from dataclasses import dataclass
from typing import List, Dict, Callable

# ---------- Parametreler ----------
STATION_COUNT = 4
BELTS_R, BELTS_C = 7, 6
FPS = 10
DT  = 1.0 / FPS

SPEED_COLLECT = 1.0
SPEED_DRAIN   = 2.0
SPEED_LINE2_DRAIN = 4.0

LOAD_LOOP_LEN_M = 120.0
SW_POS_M        = 60.0
STATION_POS_M   = {1: 10.0, 2: 30.0, 3: 80.0, 4: 100.0}

BELT_LEN_M    = 8.0
LINE2_LEN_M   = 30.0
UNL_LEN_M     = 15.0

SPAWN_RATES = (1.0, 1.0, 1.0, 1.0)

def serpentine_order(rows:int, cols:int) -> List[int]:
    order = []
    for r in range(rows):
        row = list(range((r*cols)+1, (r+1)*cols+1))
        if r % 2 == 1: row.reverse()
        order += row
    return order

SERP_ORDER = serpentine_order(BELTS_R, BELTS_C)

@dataclass
class Moving:
    id: int
    seg: str          
    pos: float
    length: float
    speed: float
    wrap: bool = False 

    def step(self, dt: float):
        if self.wrap:
            self.pos = (self.pos + self.speed * dt) % self.length
        else:
            self.pos += self.speed * dt

    @property
    def done(self) -> bool:
        return (not self.wrap) and (self.pos >= self.length - 1e-9)

class ConveyorSystem:
    def __init__(self):
        self.mode = "COLLECT"
        self.t = 0.0
        self.next_id = 1
        self.rr = 0

        self.load_loop: List[Moving] = []
        self.belts: Dict[int, List[Moving]] = {i:[] for i in range(1, BELTS_R*BELTS_C+1)}
        self.line2: List[Moving] = []
        self.unl1: List[Moving] = []
        self.unl2: List[Moving] = []
        self.done_log: List[int] = []

        self.on_unloaded: Callable[[int,str,float], None] | None = None

        self._belt_gap = 0.35 * BELT_LEN_M

    def _speed_for(self, seg:str) -> float:
        if self.mode == "COLLECT":
            if seg == "LOAD":       return SPEED_COLLECT
            if seg.startswith("B"): return SPEED_COLLECT
            if seg in ("L2","U1","U2"): return 0.0
        else:
            if seg == "L2":         return SPEED_LINE2_DRAIN
            if seg.startswith("B"): return SPEED_DRAIN
            if seg in ("U1","U2"):  return SPEED_DRAIN
        return 0.0

    def _spawn(self):
        for s, rps in enumerate(SPAWN_RATES, start=1):
            lam = rps * DT
            n = int(lam)
            if random.random() < (lam - n): n += 1
            for _ in range(n):
                self.load_loop.append(
                    Moving(
                        self.next_id, "LOAD",
                        STATION_POS_M[s] % LOAD_LOOP_LEN_M,
                        LOAD_LOOP_LEN_M,
                        self._speed_for("LOAD"),
                        wrap=True
                    )
                )
                self.next_id += 1

    def _step_load_loop(self):
        if not self.load_loop: return
        sp = self._speed_for("LOAD")
        arrived: List[Moving] = []
        for m in self.load_loop:
            prev = m.pos
            m.speed = sp
            m.step(DT)
            now = m.pos
            crossed = False
            if sp > 0:
                if prev <= SW_POS_M <= now and now - prev <= LOAD_LOOP_LEN_M/2:
                    crossed = True
                if prev > now:  
                    if SW_POS_M >= prev or SW_POS_M <= now:
                        crossed = True
            if crossed:
                arrived.append(m)

        if arrived:
            arrived.sort(key=lambda m: m.pos)
            for m in arrived:
                b = SERP_ORDER[self.rr % (BELTS_R*BELTS_C)]
                self.rr += 1
                self.belts[b].append(Moving(m.id, f"B{b}", 0.0, BELT_LEN_M, self._speed_for("B")))
            ids = {x.id for x in arrived}
            self.load_loop = [m for m in self.load_loop if m.id not in ids]

    def _step_belts(self):
        sp = self._speed_for("B")
        allow_exit = (self.mode == "DRAIN")
        GAP = self._belt_gap

        for idx in SERP_ORDER:
            seg = self.belts[idx]
            if not seg: continue

            seg.sort(key=lambda m: m.pos, reverse=True)

            leader = seg[0]
            target = leader.pos + sp * DT
            leader.pos = target if allow_exit else min(target, BELT_LEN_M)

            for i in range(1, len(seg)):
                ahead = seg[i-1]
                max_pos = ahead.pos - GAP
                if not allow_exit:
                    max_pos = min(max_pos, BELT_LEN_M)
                seg[i].pos = max(0.0, min(seg[i].pos + sp * DT, max_pos))

            if allow_exit:
                keep = []
                for m in seg:
                    if m.pos >= BELT_LEN_M - 1e-9:
                        self.line2.append(Moving(m.id, "L2", 0.0, LINE2_LEN_M, self._speed_for("L2")))
                    else:
                        keep.append(m)
                self.belts[idx] = keep

    def _step_line2(self):
        if not self.line2: return
        for m in self.line2:
            m.speed = self._speed_for("L2")
            m.step(DT)
        arrived = [m for m in self.line2 if m.done]
        if not arrived: return
        ids = {m.id for m in arrived}
        self.line2 = [m for m in self.line2 if m.id not in ids]
        for m in arrived:
            if (self.rr % 2) == 0:
                self.unl1.append(Moving(m.id, "U1", 0.0, UNL_LEN_M, self._speed_for("U1")))
            else:
                self.unl2.append(Moving(m.id, "U2", 0.0, UNL_LEN_M, self._speed_for("U2")))
            self.rr += 1

    def _step_unloads(self):
        if self.unl1:
            for m in self.unl1:
                m.speed = self._speed_for("U1")
                m.step(DT)
            done = [m for m in self.unl1 if m.done]
            if done:
                self.unl1 = [m for m in self.unl1 if m not in done]
                for m in done:
                    self.done_log.append(m.id)
                    if self.on_unloaded:
                        try: self.on_unloaded(m.id, "U1", self.t)
                        except Exception: pass

        if self.unl2:
            for m in self.unl2:
                m.speed = self._speed_for("U2")
                m.step(DT)
            done = [m for m in self.unl2 if m.done]
            if done:
                self.unl2 = [m for m in self.unl2 if m not in done]
                for m in done:
                    self.done_log.append(m.id)
                    if self.on_unloaded:
                        try: self.on_unloaded(m.id, "U2", self.t)
                        except Exception: pass

    def tick(self):
        self.t += DT
        self._spawn()
        self._step_load_loop()
        self._step_belts()
        self._step_line2()
        self._step_unloads()

    def toggle_mode(self):
        self.mode = "DRAIN" if self.mode == "COLLECT" else "COLLECT"

    def set_mode(self, mode: str):
        assert mode in ("COLLECT", "DRAIN")
        self.mode = mode

    def snapshot(self) -> Dict[str, int | float]:
        belts_q = sum(len(self.belts[b]) for b in self.belts)
        return {
            "mode": self.mode,
            "t": self.t,
            "in_load": len(self.load_loop),
            "in_belts": belts_q,
            "in_l2": len(self.line2),
            "in_u1": len(self.unl1),
            "in_u2": len(self.unl2),
            "done": len(self.done_log),
        }

if __name__ == "__main__":
    sys = ConveyorSystem()
    sys.on_unloaded = lambda iid, at, ts: None 

    print("Başladı. R: DRAIN/COLLECT toggle, Q: çıkış")
    try:
        import msvcrt 
        while True:
            start = time.time()

            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("q","Q"):
                    break
                if ch in ("r","R"):
                    sys.toggle_mode()
                    print(f"-> Mode: {sys.mode}")

            sys.tick()
            if int(sys.t) != int(sys.t - DT):
                print(sys.snapshot())

            elapsed = time.time() - start
            time.sleep(max(0.0, DT - elapsed))
    except KeyboardInterrupt:
        pass
    print("Durdu.")
