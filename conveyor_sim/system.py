import random
from typing import List, Dict, Callable, Optional

from config import (
    BELTS_R, BELTS_C, DT,
    SPEED_COLLECT, SPEED_DRAIN, SPEED_LINE2_DRAIN,
    LOAD_LOOP_LEN_M, SW_POS_M, STATION_POS_M,
    BELT_LEN_M, LINE2_LEN_M, UNL_LEN_M,
    SPAWN_RATES, HANG_DURATION_S, DRAIN_WINDOW_S
)
from ordering import serpentine_order
from moving import Moving

SERP_ORDER = serpentine_order(BELTS_R, BELTS_C)

class ConveyorSystem:
    def __init__(self):
        self.mode = "COLLECT"
        self.hang_started_at: Optional[float] = None

        self._ignore_gaps = False
        self._drain_speed_belts = SPEED_DRAIN
        self._drain_speed_line2 = SPEED_LINE2_DRAIN

        self.t = 0.0
        self.next_id = 1
        self.rr = 0 

        self.load_loop: List[Moving] = []
        self.belts: Dict[int, List[Moving]] = {i: [] for i in range(1, BELTS_R*BELTS_C+1)}
        self.line2: List[Moving] = []
        self.unl1: List[Moving] = []
        self.unl2: List[Moving] = []
        self.done_log: List[int] = []

        self.on_unloaded: Optional[Callable[[int, str, float], None]] = None

        self._belt_gap = 0.35 * BELT_LEN_M

    def _compute_and_set_drain_speeds(self):
        """Mevcut durumdan en kötü parçanın kalan yoluna göre
        15 dk içinde boşalacak minimum hızları hesaplar."""
        def worst_remaining_distance(m: Moving) -> float:
            if m.seg.startswith("B"):
                return max(0.0, BELT_LEN_M - m.pos) + LINE2_LEN_M + UNL_LEN_M
            if m.seg == "L2":
                return max(0.0, LINE2_LEN_M - m.pos) + UNL_LEN_M
            if m.seg in ("U1", "U2"):
                return max(0.0, UNL_LEN_M - m.pos)
            if m.seg == "LOAD":
                return BELT_LEN_M + LINE2_LEN_M + UNL_LEN_M
            return BELT_LEN_M + LINE2_LEN_M + UNL_LEN_M

        all_items: List[Moving] = []
        all_items += self.load_loop
        for b in self.belts.values():
            all_items += b
        all_items += self.line2 + self.unl1 + self.unl2

        worst = 0.0
        for m in all_items:
            worst = max(worst, worst_remaining_distance(m))

        min_speed = worst / max(1e-6, DRAIN_WINDOW_S)
        safety = 1.2  
        self._drain_speed_belts = max(SPEED_DRAIN, safety * min_speed)
        self._drain_speed_line2 = max(SPEED_LINE2_DRAIN, safety * min_speed)

    def _speed_for(self, seg: str) -> float:
        if self.mode == "COLLECT":
            if seg == "LOAD":       return SPEED_COLLECT
            if seg.startswith("B"): return SPEED_COLLECT
            if seg in ("L2", "U1", "U2"): return 0.0

        elif self.mode == "DRAIN":
            if seg == "LOAD":       return 0.0
            if seg.startswith("B"): return self._drain_speed_belts
            if seg == "L2":         return self._drain_speed_line2
            if seg in ("U1", "U2"): return self._drain_speed_belts

        elif self.mode == "HANG":
            if seg == "LOAD":       return SPEED_COLLECT
            if seg.startswith("B"): return 0.0
            if seg in ("L2", "U1", "U2"): return 0.0

        return 0.0

    def _enter_hang(self):
        """Askıda bekleme – tüm parçalar yalnızca BELT üzerinde bekler.
        L2/U1/U2’de bir şey varsa rastgele bir BELT ve konuma taşınır ve durdurulur."""
        self.mode = "HANG"
        self.hang_started_at = self.t
        self._ignore_gaps = False

        carry = self.line2 + self.unl1 + self.unl2
        self.line2.clear()
        self.unl1.clear()
        self.unl2.clear()

        for m in carry:
            b = random.randint(1, BELTS_R * BELTS_C)
            pos = random.uniform(0.0, BELT_LEN_M)
            self.belts[b].append(Moving(m.id, f"B{b}", pos, BELT_LEN_M, 0.0))

        for seg in self.belts.values():
            for m in seg:
                m.speed = 0.0

    def toggle_mode(self):
        """COLLECT <-> DRAIN geçişi. DRAIN’e geçerken 15dk hedef hızlarını hesaplar."""
        if self.mode != "DRAIN":
            self.mode = "DRAIN"
            self._ignore_gaps = True  
            self._compute_and_set_drain_speeds()
            for m in self.load_loop: m.speed = self._speed_for("LOAD")
            for seg in self.belts.values():
                for m in seg: m.speed = self._speed_for("B")
            for m in self.line2: m.speed = self._speed_for("L2")
            for m in self.unl1: m.speed = self._speed_for("U1")
            for m in self.unl2: m.speed = self._speed_for("U2")
        else:
            self.mode = "COLLECT"
            self._ignore_gaps = False

    def set_mode(self, mode: str):
        assert mode in ("COLLECT", "DRAIN", "HANG")
        if mode == "HANG":
            self._enter_hang()
            return
        self.mode = mode
        self._ignore_gaps = (mode == "DRAIN")

    def _spawn(self):
        """İstasyon başına DT oranında yeni yük doğurur (Poisson ~)."""
        for s, rps in enumerate(SPAWN_RATES, start=1):
            lam = rps * DT
            n = int(lam)
            if random.random() < (lam - n):
                n += 1
            for _ in range(n):
                self.load_loop.append(
                    Moving(
                        self.next_id, "LOAD",
                        STATION_POS_M[s] % LOAD_LOOP_LEN_M,
                        LOAD_LOOP_LEN_M,
                        SPEED_COLLECT,
                        wrap=True
                    )
                )
                self.next_id += 1

    def _step_load_loop(self):
        if not self.load_loop:
            return
        sp = self._speed_for("LOAD") or 0.0
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

        if not arrived:
            return

        arrived.sort(key=lambda x: x.pos)
        for m in arrived:
            if self.mode == "HANG":
                b = random.randint(1, BELTS_R * BELTS_C)
                pos = random.uniform(0.0, BELT_LEN_M)
                self.belts[b].append(Moving(m.id, f"B{b}", pos, BELT_LEN_M, 0.0))
            else:
                b = SERP_ORDER[self.rr % (BELTS_R * BELTS_C)]
                self.rr += 1
                self.belts[b].append(Moving(m.id, f"B{b}", 0.0, BELT_LEN_M, self._speed_for("B")))

        ids = {x.id for x in arrived}
        self.load_loop = [m for m in self.load_loop if m.id not in ids]

    def _step_belts(self):
        sp = self._speed_for("B") or 0.0
        allow_exit = (self.mode == "DRAIN")
        GAP = self._belt_gap
        ignore_gaps = self._ignore_gaps

        for idx in SERP_ORDER:
            seg = self.belts[idx]
            if not seg:
                continue

            seg.sort(key=lambda m: m.pos, reverse=True)

            leader = seg[0]
            target = leader.pos + sp * DT
            leader.pos = target if allow_exit else min(target, BELT_LEN_M)

            for i in range(1, len(seg)):
                if ignore_gaps:
                    seg[i].pos = max(0.0, seg[i].pos + sp * DT)
                else:
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
        if not self.line2:
            return
        for m in self.line2:
            m.speed = self._speed_for("L2")
            m.step(DT)
        arrived = [m for m in self.line2 if m.done]
        if not arrived:
            return
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
                        try:
                            self.on_unloaded(m.id, "U1", self.t)
                        except Exception:
                            pass

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
                        try:
                            self.on_unloaded(m.id, "U2", self.t)
                        except Exception:
                            pass

    def tick(self):
        self.t += DT
        self._spawn()
        self._step_load_loop()
        self._step_belts()
        self._step_line2()
        self._step_unloads()

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
