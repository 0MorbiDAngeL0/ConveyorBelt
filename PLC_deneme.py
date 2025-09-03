import time
from dataclasses import dataclass

# --- Platform: Windows'ta non-blocking klavye için msvcrt ---
try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False
    # Linux/Mac'te basit bir alternatif: inputs'i
    # kod içinde programatik olarak değiştir ya da
    # keyboard kütüphanesi kullan (sudo gerektirebilir).

# --- Yardımcı bloklar: kenar dedektörü & TON timer ---

@dataclass
class EdgeDetector:
    prev: bool = False
    def rising(self, now: bool) -> bool:
        r = (not self.prev) and now
        self.prev = now
        return r
    def falling(self, now: bool) -> bool:
        f = self.prev and (not now)
        self.prev = now
        return f

@dataclass
class TON:
    pt: float  # preset time (s)
    _start_t: float = None
    q: bool = False  # çıkış
    et: float = 0.0  # elapsed time

    def update(self, in_: bool, tnow: float):
        if in_:
            if self._start_t is None:
                self._start_t = tnow
                self.et = 0.0
                self.q = False
            else:
                self.et = tnow - self._start_t
                self.q = self.et >= self.pt
        else:
            # TON reset
            self._start_t = None
            self.et = 0.0
            self.q = False

# --- I/O tanımları (etiketler) ---

@dataclass
class Inputs:
    StartPB: bool = False     # Start push-button (NO, anlık)
    StopPB: bool = False      # Stop push-button (NO, anlık)
    EStop: bool = False       # E-Stop (kilitli)
    SensorFull: bool = False  # Konveyör dolu sensörü

@dataclass
class Outputs:
    Motor: bool = False       # Konveyör motoru

# --- PLC Program (konveyör mantığı) ---

class ConveyorPLC:
    def __init__(self):
        self.inp = Inputs()
        self.out = Outputs()
        self._ed_start = EdgeDetector()
        self._ed_stop = EdgeDetector()
        self._ton_full_stop = TON(pt=3.0)  # Dolu sensörü görünce 3 sn sonra dursun

    def scan(self, tnow: float, dt: float):
        # 1) Kenar tespiti (Start/Stop anlık butonlar)
        start_edge = self._ed_start.rising(self.inp.StartPB)
        stop_edge  = self._ed_stop.rising(self.inp.StopPB)

        # 2) Zamanlayıcı: SensorFull TRUE ise TON saymaya başlasın
        self._ton_full_stop.update(self.inp.SensorFull, tnow)

        # 3) Mühürleme devresi (seal-in):
        # Motor, Start'a basılınca (rising edge) çalışır;
        # Stop'a basılınca veya E-Stop aktifse veya TON tamamlandıysa durur.
        if start_edge and not self.inp.EStop:
            self.out.Motor = True

        if stop_edge or self.inp.EStop or self._ton_full_stop.q:
            self.out.Motor = False

        # 4) (Opsiyonel) Fault/Interlock'lar eklenebilir
        # Örn: emniyet kapısı, termik, hız feedback vs.

# --- UI / Simülasyon döngüsü ---

def print_help():
    print("="*72)
    print("Klavye:")
    print("  s = Start (anlık basış)")
    print("  x = Stop  (anlık basış)")
    print("  e = E-Stop (toggle)")
    print("  f = SensorFull (toggle)")
    print("  q = Çıkış")
    print("="*72)

def main():
    plc = ConveyorPLC()
    scan_time = 0.02  # 20 ms
    last_print = 0.0

    print_help()
    print("Scan başlıyor...")

    t0 = time.monotonic()
    try:
        while True:
            tnow = time.monotonic()
            dt = tnow - t0
            t0 = tnow

            # --- Klavye ile girişleri sür ---
            if HAS_MSVCRT:
                while msvcrt.kbhit():
                    ch = msvcrt.getch().decode(errors='ignore').lower()
                    if ch == 'q':
                        raise KeyboardInterrupt
                    elif ch == 's':
                        plc.inp.StartPB = True
                    elif ch == 'x':
                        plc.inp.StopPB = True
                    elif ch == 'e':
                        plc.inp.EStop = not plc.inp.EStop
                    elif ch == 'f':
                        plc.inp.SensorFull = not plc.inp.SensorFull

            # --- Scan: mantığı çalıştır ---
            plc.scan(tnow, dt)

            # --- Start/Stop butonlarını anlık yap: bir scan sonra bırak ---
            plc.inp.StartPB = False
            plc.inp.StopPB = False

            # --- Durum yazdır (200 ms'de bir) ---
            last_print += dt
            if last_print >= 0.2:
                last_print = 0.0
                print(f"Motor={plc.out.Motor} | "
                      f"EStop={plc.inp.EStop} | "
                      f"SensorFull={plc.inp.SensorFull} | "
                      f"TON_q={plc._ton_full_stop.q} et={plc._ton_full_stop.et:.1f}s")

            # --- Döngü periyodu ---
            to_sleep = scan_time - (time.monotonic() - tnow)
            if to_sleep > 0:
                time.sleep(to_sleep)

    except KeyboardInterrupt:
        print("\nÇıkılıyor... Motor kapatıldı.")
        plc.out.Motor = False

if __name__ == "__main__":
    main()
