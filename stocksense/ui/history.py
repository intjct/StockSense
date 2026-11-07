"""The right-hand 'ประวัติการวิเคราะห์' panel: every past buy/sell analysis, openable again with no website or AI call,
plus picking two buy analyses to compare."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from . import theme
from .widgets import button, clear, label, money, pill

KIND_TH = {"buy": "ซื้อ", "sell": "ขาย"}


def age_text(at: str, now: dt.datetime | None = None) -> str:
    """'วันนี้' / 'เมื่อวาน' / '3 วันก่อน' from a 'YYYY-MM-DD HH:MM' stamp."""
    try:
        t = dt.datetime.strptime(str(at)[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return str(at or "")
    days = ((now or dt.datetime.now()).date() - t.date()).days
    if days <= 0:
        return "วันนี้"
    if days == 1:
        return "เมื่อวาน"
    if days < 30:
        return f"{days} วันก่อน"
    return f"{days // 30} เดือนก่อน"


def age_days(at: str, now: dt.datetime | None = None) -> int:
    try:
        t = dt.datetime.strptime(str(at)[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return 0
    return max(0, ((now or dt.datetime.now()).date() - t.date()).days)


class HistRow(QFrame):
    def __init__(self, e: dict, on_open, on_check):
        super().__init__()
        self.e = e
        self.setObjectName("SoftCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open = on_open
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)
        self.check = None
        if e["kind"] == "buy" and e.get("has_full"):
            self.check = QCheckBox()
            self.check.setToolTip("ติ๊กเลือกไว้เทียบกัน (เลือกได้ 2 ตัว)")
            self.check.toggled.connect(lambda _on: on_check())
            lay.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(1)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(label(e["sym"], 14, True))
        top.addStretch(1)
        top.addWidget(pill(f"{e['label']} {e['score']}%", e.get("tone", "none"), 11))
        col.addLayout(top)
        col.addWidget(label(e.get("name") or e["sym"], 12, name="Soft"))
        extra = "" if e.get("has_full") else " · เก็บแค่คะแนน"
        col.addWidget(label(f"{KIND_TH.get(e['kind'], '')} · {age_text(e['at'])} · {money(e['price'])}{extra}", 11, name="Soft"))
        lay.addLayout(col, 1)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._open(self.e)
        super().mousePressEvent(ev)


class HistoryPanel(QFrame):
    def __init__(self, hist, on_open, on_compare):
        super().__init__()
        self.hist, self._open, self._compare = hist, on_open, on_compare
        self.rows: list[HistRow] = []
        self.setObjectName("HistPanel")
        self.setFixedWidth(310)
        self.setStyleSheet(
            f"QFrame#HistPanel {{ background:{theme.BG.name()}; border-left:1px solid {theme.LINE.name()}; }}"
            f"QCheckBox::indicator {{ width:16px; height:16px; border:1.5px solid #A9A9A2; border-radius:5px; background:#FFFFFF; }}"
            f"QCheckBox::indicator:hover {{ border-color:{theme.INK.name()}; }}"
            f"QCheckBox::indicator:checked {{ background:{theme.LIME.name()}; border:2px solid {theme.INK.name()}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(8)
        lay.addWidget(label("ประวัติการวิเคราะห์", 15, True))
        lay.addWidget(label("กดที่แถวเพื่อเปิดผลเดิม ไม่ต้องรอ ไม่เสียโควตา", 11, name="Soft", wrap=True))
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        self.list_l = QVBoxLayout(holder)
        self.list_l.setContentsMargins(0, 0, 0, 0)
        self.list_l.setSpacing(6)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setWidget(holder)
        sc.setStyleSheet("QScrollArea{background:transparent;border:none;} QScrollArea > QWidget > QWidget{background:transparent;}")
        lay.addWidget(sc, 1)
        self.hint = label("", 11, name="Soft", wrap=True)
        lay.addWidget(self.hint)
        self.b_cmp = button("เปรียบเทียบ 2 ตัว", "Dark", 13, True)
        self.b_cmp.clicked.connect(self._go_compare)
        lay.addWidget(self.b_cmp)
        self.refresh()

    def refresh(self):
        clear(self.list_l)
        self.rows = []
        entries = self.hist.entries()
        if not entries:
            self.list_l.addWidget(label("ยังไม่มีประวัติ ลองกดวิเคราะห์ซื้อหรือขายสักตัวก่อน", 12, name="Soft", wrap=True))
        for e in entries:
            r = HistRow(e, self._open, self._checked_changed)
            self.rows.append(r)
            self.list_l.addWidget(r)
        self.list_l.addStretch(1)
        self._checked_changed()

    def checked(self) -> list[dict]:
        return [r.e for r in self.rows if r.check is not None and r.check.isChecked()]

    def _checked_changed(self):
        n = len(self.checked())
        self.hint.setText("ติ๊กช่องหน้าหุ้น 2 ตัวจากผลวิเคราะห์ซื้อ แล้วกดเปรียบเทียบ" if n == 0 else
                          "เลือกแล้ว 1 ตัว เลือกอีก 1 ตัว" if n == 1 else
                          "เลือกแล้ว 2 ตัว กดเปรียบเทียบได้เลย" if n == 2 else
                          "เลือกได้ไม่เกิน 2 ตัว เอาติ๊กออกก่อน")

    def _go_compare(self):
        c = self.checked()
        if len(c) != 2:
            self._checked_changed()
            return
        self._compare(c[0], c[1])
