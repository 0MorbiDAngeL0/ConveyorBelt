from typing import List

def serpentine_order(rows: int, cols: int) -> List[int]:
    order = []
    for r in range(rows):
        row = list(range((r*cols)+1, (r+1)*cols+1))
        if r % 2 == 1: row.reverse()
        order += row
    return order