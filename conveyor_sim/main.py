import time
from system import ConveyorSystem
from config import DT

def run():
    sys = ConveyorSystem()
    sys.on_unloaded = lambda iid, at, ts: None

    print("Başladı. R: DRAIN/COLLECT, P: PENÇE/ASKI, H: HANG (opsiyonel), Q: çıkış")
    try:
        # Windows'ta anlık klavye için msvcrt
        try:
            import msvcrt
            has_msvcrt = True
        except ImportError:
            has_msvcrt = False
            print("(Uyarı) msvcrt yok: tuş algılama kapalı; simülasyon akacak.")

        while True:
            start = time.time()

            ch = None
            if has_msvcrt and msvcrt.kbhit():
                ch = msvcrt.getwch().lower()

            if ch == "q":
                break
            elif ch == "r":
                sys.toggle_mode()
                print(f"-> Mode: {sys.mode}")
            elif ch == "p":
                sys.pick_and_hang()
                print("-> P: LOAD -> (L1/BELT/LOAD rastgele) taşı ve dondur")
            elif ch == "h":
                sys._enter_hang()   # opsiyonel manuel HANG
                print("-> Mode: HANG (askıda bekleme)")

            sys.tick()

            # Her tam saniyede bir snapshot yaz
            if int(sys.t) != int(sys.t - DT):
                print(sys.snapshot(), flush=True)

            elapsed = time.time() - start
            time.sleep(max(0.0, DT - elapsed))

    except KeyboardInterrupt:
        pass
    print("Durdu.")

if __name__ == "__main__":
    run()
