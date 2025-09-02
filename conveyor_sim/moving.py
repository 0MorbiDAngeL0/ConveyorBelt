from dataclasses import dataclass

@dataclass
class Moving:
    id: int
    seg: str          
    pos: float
    length: float
    speed: float
    wrap: bool = False
    created_at: float = 0.0       
    entered_area_at: float = 0.0  
    barcode: str = ""

    def step(self, dt: float):
        sp = 0.0 if self.speed is None else self.speed
        if self.wrap:
            self.pos = (self.pos + sp * dt) % self.length
        else:
            self.pos += sp * dt

    @property
    def done(self) -> bool:
        return (not self.wrap) and (self.pos >= self.length - 1e-9)
