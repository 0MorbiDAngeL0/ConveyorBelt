from __future__ import annotations
import curses, time, random
from dataclasses import dataclass
from typing import List, Dict, Tuple

STATION_COUNT = 4
BELTS_R, BELTS_C = 7, 6
FPS = 10
DT  = 1.0 / FPS

SPEED_COLLECT = 1.0
SPEED_DRAIN   = 2.0
SPEED_LINE2_DRAIN = 4.0
SPEED_LINE_DRAIN = 4.0

LOAD_LOOP_LEN_M = 120.0
SW_POS_M        = 60.0
STATION_POS_M   = {1: 10.0, 2: 30.0, 3: 80.0, 4: 100.0}

BELT_LEN_M    = 8.0
LINE2_LEN_M   = 30.0
LINE_LEN_M   = 30.0
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


CELLS_LOAD = 60
CELLS_BELT = 18
CELLS_LINE2= 18
CELLS_UNL  = 14

def clamp(v,a,b): return a if v<a else b if v>b else v

def safe_addstr(win, y, x, s):
    maxy, maxx = win.getmaxyx()
    if y < 0 or y >= maxy or x >= maxx: return
    if x < 0:
        s = s[-x:]; x = 0
    if not s: return
    s = s[:maxx-x]
    try: win.addstr(y, x, s)
    except: pass

def safe_addch(win, y, x, ch):
    maxy, maxx = win.getmaxyx()
    if 0 <= y < maxy and 0 <= x < maxx:
        try: win.addch(y, x, ch)
        except: pass

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

class System:
    def __init__(self):
        self.mode = "COLLECT"
        self.t = 0.0
        self.next_id = 1
        self.rr = 0

        self.load_loop: List[Moving] = [] 
        self.swap_q: List[int] = []

        self.belts: Dict[int, List[Moving]] = {i:[] for i in range(1, BELTS_R*BELTS_C+1)}
        self.line2: List[Moving] = []
        self.unl1: List[Moving] = []
        self.unl2: List[Moving] = []
        self.done_log: List[int] = []

    def speed_for(self, seg:str) -> float:
        if self.mode == "COLLECT":
            if seg in ("LOAD",): return SPEED_COLLECT
            if seg.startswith("B"): return SPEED_COLLECT     
            if seg in ("L2","U1","U2"): return 0.0
        else:
            if seg == "L2":
                return SPEED_LINE2_DRAIN
            if seg.startswith("B"):
                return SPEED_DRAIN
            if seg in ("U1","U2"):
                return SPEED_DRAIN
        return 0.0

    def spawn(self):
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
                        self.speed_for("LOAD"),
                        wrap=True
                    )
                )
                self.next_id += 1

    def step_load_loop(self):
        arrived_ids = []
        speed = self.speed_for("LOAD")
        if not self.load_loop: return
        for m in self.load_loop:
            prev = m.pos
            m.speed = speed
            m.step(DT)
            now = m.pos
            crossed = False
            if speed > 0:
                if prev <= SW_POS_M <= now and now - prev <= LOAD_LOOP_LEN_M/2:
                    crossed = True
                if prev > now: 
                    if SW_POS_M >= prev or SW_POS_M <= now:
                        crossed = True
            if crossed:
                arrived_ids.append(m.id)
        if arrived_ids:
            order = sorted(arrived_ids, key=lambda iid: next(x.pos for x in self.load_loop if x.id==iid))
            for iid in order:
                self.swap_q.append(iid)
            self.load_loop = [m for m in self.load_loop if m.id not in arrived_ids]

    def dispatch_to_belts(self):
        while self.swap_q:
            iid = self.swap_q.pop(0)
            b = SERP_ORDER[self.rr % (BELTS_R*BELTS_C)]
            self.rr += 1
            self.belts[b].append(Moving(iid, f"B{b}", 0.0, BELT_LEN_M, self.speed_for("B")))

    def step_belts(self):
        """Bantlarda konvoy hareketi.
        COLLECT: sona kadar diz ve dur; DRAIN: sona gelenler Line-2'ye düşer."""
        sp = self.speed_for("B")
        allow_exit = (self.mode == "DRAIN")
        GAP = BELT_LEN_M / max(1, (CELLS_BELT - 2))

        for idx in SERP_ORDER:
            seg = self.belts[idx]
            if not seg:
                continue

            seg.sort(key=lambda m: m.pos, reverse=True)

            leader = seg[0]
            target = leader.pos + sp * DT
            if not allow_exit:
                leader.pos = min(target, BELT_LEN_M)  
            else:
                leader.pos = target

            for i in range(1, len(seg)):
                ahead = seg[i-1]
                max_pos = ahead.pos - GAP
                if not allow_exit:
                    max_pos = min(max_pos, BELT_LEN_M)
                seg[i].pos = min(seg[i].pos + sp * DT, max_pos)

            if allow_exit:
                keep = []
                for m in seg:
                    if m.pos >= BELT_LEN_M - 1e-9:
                        self.line2.append(Moving(m.id, "L2", 0.0, LINE2_LEN_M, self.speed_for("L2")))
                    else:
                        keep.append(m)
                self.belts[idx] = keep

    def step_line2(self):
        for m in self.line2:
            m.speed = self.speed_for("L2")
            m.step(DT)
        arrived = [m for m in self.line2 if m.done]
        if not arrived:
            return
        self.line2 = [m for m in self.line2 if m not in arrived]
        for m in arrived:
            if (self.rr % 2) == 0:
                self.unl1.append(Moving(m.id, "U1", 0.0, UNL_LEN_M, self.speed_for("U1")))
            else:
                self.unl2.append(Moving(m.id, "U2", 0.0, UNL_LEN_M, self.speed_for("U2")))
            self.rr += 1

    def step_unloads(self):
        for m in self.unl1:
            m.speed = self.speed_for("U1")
            m.step(DT)
        for m in self.unl2:
            m.speed = self.speed_for("U2")
            m.step(DT)
        d1 = [m for m in self.unl1 if m.done]
        d2 = [m for m in self.unl2 if m.done]
        if d1:
            self.done_log += [m.id for m in d1]
            self.unl1 = [m for m in self.unl1 if m not in d1]
        if d2:
            self.done_log += [m.id for m in d2]
            self.unl2 = [m for m in self.unl2 if m not in d2]

    def enter_drain(self):
        if self.mode == "DRAIN": return
        self.mode = "DRAIN"

    def enter_collect(self):
        if self.mode == "COLLECT": return
        self.mode = "COLLECT"

    def toggle_mode(self):
        self.mode = "DRAIN" if self.mode == "COLLECT" else "COLLECT"

    def tick(self):
        """Her frame"""
        self.t += DT
        self.spawn()
        self.step_load_loop()
        self.dispatch_to_belts()
        self.step_belts()
        self.step_line2()
        self.step_unloads()

    def snapshot(self):
        inflight = len(self.load_loop)
        belts_q  = sum(len(self.belts[b]) for b in self.belts)
        return {
            "mode": self.mode, "t": self.t,
            "inflight": inflight, "swap": len(self.swap_q),
            "belts": belts_q, "line2": len(self.line2),
            "u1": len(self.unl1), "u2": len(self.unl2),
            "done": len(self.done_log)
        }

# ------------ ÇİZİM ------------
def draw_bar_h(win, y, x, length_cells, items_cells_positions):
    maxy, maxx = win.getmaxyx()
    if y < 0 or y >= maxy: return
    L = min(length_cells, max(3, maxx - x))
    if L < 3: return
    safe_addstr(win, y, x, "[" + "-" * (L - 2) + "]")
    for c in items_cells_positions:
        c = max(0, min(L - 3, c))
        safe_addch(win, y, x + 1 + c, ord('o'))
        

def draw_bar_v(win, y, x, length_cells, items_cells_positions):
    """
    Dikey bar: her satırda en fazla 1 parça göster.
    Aynı hücreye düşen parçalar bir üst hücreye kaydırılarak yerleştirilir.
    (Alt = r=0, Üst = r=L-1)
    """
    maxy, maxx = win.getmaxyx()
    if x < 0 or x >= maxx:
        return
    L = min(length_cells, max(1, maxy - y))
    if L < 1:
        return

    # Rayı çiz
    for i in range(L):
        safe_addch(win, y + i, x, ord('|'))

    # İstenen (ham) satırlar: 0=alt, L-1=üst (ekrandaki koordinat karşılığı: y+(L-1-r))
    rows = [max(0, min(L - 1, r)) for r in items_cells_positions]

    # Altı önce yerleştir (0,1,2,...) ve çakışmaları yukarı kaydır
    rows.sort()
    occ = [False] * L           # occ[i] -> i. satır (0=alt) dolu mu?
    for rb in rows:
        k = rb
        while k < L and occ[k]:
            k += 1              # bir üst hücreye kaydır
        if k < L:
            occ[k] = True       # yerleştir (fazlaysa görsel olarak düşer)

    # Çiz: ekranda satır i (0=alt) -> y + (L-1 - i)
    for i, filled in enumerate(occ):
        if filled:
            safe_addch(win, y + (L - 1 - i), x, ord('o'))



def layout_and_draw(stdscr, sys: System):
    stdscr.erase()
    maxy, maxx = stdscr.getmaxyx()
    minx, miny = 110, 36
    if maxx < minx or maxy < miny:
        safe_addstr(stdscr, 0, 0, f"Terminal {maxy}x{maxx} küçük. En az {miny}x{minx}.")
        stdscr.refresh(); return

    s = sys.snapshot()
    safe_addstr(stdscr, 0, 0, f"[{s['mode']}] t={s['t']:.1f}s  inflight={s['inflight']} swap={s['swap']} belts={s['belts']} line2={s['line2']} U1={s['u1']} U2={s['u2']} done={s['done']}  (R=Drain, Q=Quit)")

    ox, oy = 2, 2

    y = oy+2
    xs = []
    for m in sys.load_loop:
        c = int((m.pos / LOAD_LOOP_LEN_M) * (CELLS_LOAD-2))
        xs.append(clamp(c, 0, CELLS_LOAD-2))
    draw_bar_h(stdscr, y, ox, CELLS_LOAD, xs)
    for sid, spos in STATION_POS_M.items():
        cx = ox+1 + clamp(int((spos/LOAD_LOOP_LEN_M)*(CELLS_LOAD-2)),0,CELLS_LOAD-2)
        safe_addch(stdscr, y, cx, ord('^'))
        safe_addstr(stdscr, y-1, cx-1, f"S{sid}")
    swx = ox+1 + clamp(int((SW_POS_M/LOAD_LOOP_LEN_M)*(CELLS_LOAD-2)),0,CELLS_LOAD-2)
    safe_addch(stdscr, y, swx, ord('S')); safe_addstr(stdscr, y+1, swx-1, "SW")

    grid_ox = ox
    grid_oy = y+4
    row_h = 2
    Lb = CELLS_BELT
    idx = 1
    for r in range(BELTS_R):
        yy = grid_oy + r*row_h
        for c in range(BELTS_C):
            x = grid_ox + c*(Lb+2)
            items = sys.belts[idx]
            xs = [clamp(int((m.pos/m.length)*(Lb-2)),0,Lb-2) for m in items]
            draw_bar_h(stdscr, yy, x, Lb, xs)
            safe_addstr(stdscr, yy+1, x+Lb//2-2, f"B{idx:02d}")
            idx += 1

    l2_x = grid_ox + BELTS_C*(Lb+2) + 4
    l2_y = grid_oy
    Lv = CELLS_LINE2
    ys = [clamp(int((m.pos/m.length)*(Lv-1)),0,Lv-1) for m in sys.line2]
    draw_bar_v(stdscr, l2_y, l2_x, Lv, ys)

    u1_y = l2_y + 1
    u2_y = l2_y + Lv - 2
    u_x  = l2_x + 4
    Lu   = CELLS_UNL
    xs = [clamp(int((m.pos/m.length)*(Lu-2)),0,Lu-2) for m in sys.unl1]
    draw_bar_h(stdscr, u1_y, u_x, Lu, xs)
    safe_addstr(stdscr, u1_y+1, u_x+Lu//2-2, "U1")
    xs = [clamp(int((m.pos/m.length)*(Lu-2)),0,Lu-2) for m in sys.unl2]
    draw_bar_h(stdscr, u2_y, u_x, Lu, xs)
    safe_addstr(stdscr, u2_y+1, u_x+Lu//2-2, "U2")

    stdscr.refresh()

def main(stdscr):
    curses.curs_set(0); stdscr.nodelay(True); stdscr.timeout(0)
    sys = System()
    last = time.time()
    while True:
        now = time.time()
        delay = DT - (now-last)
        if delay > 0: time.sleep(delay)
        last = time.time()

        ch = stdscr.getch()
        if ch in (ord('q'), ord('Q')): break
        if ch in (ord('r'), ord('R')): sys.toggle_mode()

        sys.tick()
        layout_and_draw(stdscr, sys)

if __name__ == "__main__":
    curses.wrapper(main)
