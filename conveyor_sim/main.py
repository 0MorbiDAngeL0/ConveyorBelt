import time
from system import ConveyorSystem
from config import DT

def run():
    sys = ConveyorSystem()
    sys.on_unloaded = lambda iid, at, ts: None

    print("Başladı. R: DRAIN/COLLECT toggle, Q: çıkış")
    try:
        # Windows için msvcrt; diğer platformlarda sadece akan simülasyon
        try:
            import msvcrt
            has_msvcrt = True
        except ImportError:
            has_msvcrt = False

        while True:
            start = time.time()

            if has_msvcrt and msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("q","Q"):
                    break
                if ch in ("r","R"):
                    sys.toggle_mode()
                    print(f"-> Mode: {sys.mode}")

            sys.tick()
            # her tam saniyede bir snapshot yaz
            if int(sys.t) != int(sys.t - DT):
                print(sys.snapshot())

            elapsed = time.time() - start
            time.sleep(max(0.0, DT - elapsed))
    except KeyboardInterrupt:
        pass
    print("Durdu.")

if __name__ == "__main__":
    run()
