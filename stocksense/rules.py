"""เงื่อนไขเปลี่ยนใจ: rules the person sets (or accepts) while calm, checked every time the program opens.

Pure functions: given a rule and the facts about one holding, say whether it has
happened ("hit"), is close ("near"), is fine ("ok") or can't be told ("unknown")."""
from __future__ import annotations

KINDS = {
    "price_below": {"title": "ราคาหลุดต่ำกว่า", "unit": "$", "default": None, "step": 1.0, "lo": 0.01, "hi": 1e6},
    "loss_pct": {"title": "ขาดทุนจากต้นทุนเกิน", "unit": "%", "default": 20.0, "step": 1.0, "lo": 1.0, "hi": 99.0},
    "weight_above": {"title": "น้ำหนักในพอร์ตเกิน", "unit": "%", "default": 40.0, "step": 1.0, "lo": 5.0, "hi": 100.0},
    "earnings_miss": {"title": "กำไรไตรมาสล่าสุดแย่กว่าที่คาด", "unit": "", "default": None, "step": 0, "lo": 0, "hi": 0},
}
NEAR_PRICE = 1.05          # within 5% above the line counts as "near"
MISS_PCT = -2.0            # earnings count as a miss when worse than expected by more than 2%


def make(kind: str, value=None) -> dict:
    d = KINDS[kind]["default"] if value is None else value
    return {"kind": kind, "value": d, "on": True}


def default_rules(price: float | None, support: float | None, has_earnings: bool = True) -> list[dict]:
    """What the program suggests: floor from the chart, a loss limit, a weight limit, an earnings miss."""
    out = []
    line = support or (price * 0.85 if price else None)
    if line:
        out.append(make("price_below", round(float(line), 2)))
    out.append(make("loss_pct"))
    out.append(make("weight_above"))
    if has_earnings:
        out.append(make("earnings_miss"))
    return out


def clean(rules) -> list[dict]:
    """Keeps only well-formed rules (the file may be edited by hand)."""
    out = []
    for r in rules or []:
        if not isinstance(r, dict) or r.get("kind") not in KINDS:
            continue
        v = r.get("value")
        try:
            v = None if v is None else float(v)
        except (TypeError, ValueError):
            continue
        if KINDS[r["kind"]]["unit"] and not v:
            continue
        out.append({"kind": r["kind"], "value": v, "on": bool(r.get("on", True))})
    return out


def describe(rule: dict) -> str:
    k = KINDS[rule["kind"]]
    if rule["kind"] == "earnings_miss":
        return k["title"]
    v = rule["value"]
    return f"{k['title']} ${v:,.2f}" if k["unit"] == "$" else f"{k['title']} {v:g}%"


def evaluate(rule: dict, ctx: dict) -> dict:
    """ctx: price, avg_price, weight_pct, surprise_pct (None if unknown).

    Returns {state: hit|near|ok|unknown|off, text}."""
    if not rule.get("on", True):
        return {"state": "off", "text": "ปิดอยู่"}
    kind, v = rule["kind"], rule.get("value")
    price = ctx.get("price")
    if kind == "price_below":
        if price is None or not v:
            return {"state": "unknown", "text": "ยังไม่รู้ราคา"}
        gap = (price - v) / v * 100
        if price < v:
            return {"state": "hit", "text": f"หลุดแล้ว (ต่ำกว่า {abs(gap):.0f}%)"}
        if price < v * NEAR_PRICE:
            return {"state": "near", "text": f"ใกล้ถึง · ห่าง {gap:.0f}%"}
        return {"state": "ok", "text": f"ยังไม่ถึง · ห่าง {gap:.0f}%"}
    if kind == "loss_pct":
        avg = ctx.get("avg_price")
        if price is None or not avg:
            return {"state": "unknown", "text": "ยังไม่รู้ราคา"}
        loss = (avg - price) / avg * 100
        if loss >= v:
            return {"state": "hit", "text": f"ถึงแล้ว (ขาดทุน {loss:.0f}%)"}
        if loss >= v * 0.75:
            return {"state": "near", "text": f"ใกล้ถึง · ตอนนี้ขาดทุน {loss:.0f}%"}
        return {"state": "ok", "text": "ตอนนี้กำไรอยู่" if loss <= 0 else f"ยังไม่ถึง · ขาดทุน {loss:.0f}%"}
    if kind == "weight_above":
        w = ctx.get("weight_pct")
        if w is None:
            return {"state": "unknown", "text": "ยังไม่รู้สัดส่วน"}
        if w >= v:
            return {"state": "hit", "text": f"เกินแล้ว ({w:.0f}%)"}
        if w >= v * 0.9:
            return {"state": "near", "text": f"ใกล้ถึง · ตอนนี้ {w:.0f}%"}
        return {"state": "ok", "text": f"ยังไม่ถึง · ตอนนี้ {w:.0f}%"}
    if kind == "earnings_miss":
        s = ctx.get("surprise_pct")
        if s is None:
            return {"state": "unknown", "text": "ยังไม่มีข้อมูลผลประกอบการ"}
        if s < MISS_PCT:
            return {"state": "hit", "text": f"เกิดแล้ว (แย่กว่าคาด {abs(s):.0f}%)"}
        return {"state": "ok", "text": "ยังไม่เกิด" if s <= 0 else "ไตรมาสล่าสุดดีกว่าที่คาด"}
    return {"state": "unknown", "text": ""}


def evaluate_all(rules, ctx: dict) -> list[dict]:
    return [{"rule": r, "desc": describe(r), **evaluate(r, ctx)} for r in clean(rules)]


def summary(results: list[dict]) -> dict:
    return {"hit": sum(1 for r in results if r["state"] == "hit"), "near": sum(1 for r in results if r["state"] == "near")}
