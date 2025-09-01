# test_sim.py
from __future__ import annotations
import time
from typing import List, Tuple

# Eğer sınıf aynı dosyada değilse:
from conveyor_core import ConveyorSystem, DT

def run_scenario(toggles: List[float], T_end: float = 20.0) -> None:
    sys = ConveyorSystem()

    # basit log: her tam saniyede yaz
    def log_snapshot(tag=""):
        snap = sys.snapshot()
        print(f"{tag} t={snap['t']:.1f}s mode={snap['mode']} "
              f"load={snap['in_load']} belts={snap['in_belts']} "
              f"l2={snap['in_l2']} u1={snap['in_u1']} u2={snap['in_u2']} done={snap['done']}")

    # toggle zamanlarını saniye -> tick sayısına çevir
    toggle_ticks = set(int(x/DT) for x in toggles)

    last_int_sec = -1
    total_ticks = int(T_end/DT)
    for k in range(total_ticks):
        # toggle anı mı?
        if k in toggle_ticks:
            sys.toggle_mode()
            log_snapshot(tag="TOGGLE ->")

        sys.tick()

        # her tam saniyede satır yaz
        if int(sys.t) != last_int_sec:
            last_int_sec = int(sys.t)
            log_snapshot()

        # bazı otomatik kontroller (invariants)
        # Toplam üretilen = next_id-1
        produced = sys.next_id - 1
        in_system = (len(sys.load_loop)
                     + sum(len(v) for v in sys.belts.values())
                     + len(sys.line2)
                     + len(sys.unl1)
                     + len(sys.unl2)
                     + len(sys.done_log))
        assert produced == in_system, f"Sayım uyuşmazlığı! produced={produced} in_system={in_system}"

        # DRAIN modunda bantlar boşalırken line2 artmalı (zamanla u1/u2’ye akar)
        # Bu bir “trend” testi değil ama minimum mantık kontrolü:
        if sys.mode == "DRAIN":
            pass  # burada ek trend testleri istersen eklersin

        # COLLECT moduna döndüğünde Line2/U1/U2 duruyorsa (senin mevcut politikan), bu bilinçli mi?
        # Eğer “residual drain” istiyorsan alttaki patch’i uygulamalısın (bkz. bölüm 2).

    # final rapor
    print("\n--- FINAL ---")
    log_snapshot()

if __name__ == "__main__":
    # 5. saniyede DRAIN, 12. saniyede tekrar COLLECT; toplam 20 sn koş.
    run_scenario(toggles=[5.0, 12.0], T_end=20.0)
