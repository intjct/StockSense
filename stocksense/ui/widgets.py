"""Small building blocks shared by every screen."""
from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from . import theme


# ---------------------------------------------------------------- text helpers

def money(v, dec: int = 2) -> str:
    if v is None:
        return "-"
    return f"-${abs(v):,.{dec}f}" if v < 0 else f"${v:,.{dec}f}"


def baht(v) -> str:
    return "-" if v is None else f"฿{v:,.0f}"


def signed_pct(v, dec: int = 1) -> str:
    return "-" if v is None else f"{'+' if v >= 0 else '−'}{abs(v):.{dec}f}%"


def big_money(v) -> str:
    if v is None:
        return "-"
    a, s = abs(v), "−" if v < 0 else ""
    if a >= 1e9:
        return f"{s}${a / 1e9:,.1f}B"
    if a >= 1e6:
        return f"{s}${a / 1e6:,.0f}M"
    return f"{s}${a:,.0f}"


def label(text: str = "", px: float = 13, bold: bool = False, name: str = "", wrap: bool = False,
          color: QColor | None = None) -> QLabel:
    l = QLabel(text)
    l.setFont(theme.font(px, bold))
    if name:
        l.setObjectName(name)
    if wrap:
        l.setWordWrap(True)
    if color is not None:
        l.setStyleSheet(f"color:{color.name()}; background: transparent;")
    l.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse if wrap else Qt.TextInteractionFlag.NoTextInteraction)
    return l


def button(text: str, name: str, px: float = 13, bold: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(name)
    b.setFont(theme.font(px, bold))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def card(name: str = "Card", margins=(16, 14, 16, 14), spacing: int = 8) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName(name)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return f, lay


def sep() -> QFrame:
    s = QFrame()
    s.setObjectName("Sep")
    s.setFixedHeight(1)
    return s


def pill(text: str, tone: str = "good", px: float = 12) -> QLabel:
    l = QLabel(text)
    l.setFont(theme.font(px, True))
    if tone == "lime":
        bg, fg = theme.LIME, theme.INK
    else:
        bg, fg = theme.TONE_BG.get(tone, theme.SOFT), theme.TONE_FG.get(tone, theme.TEXT_SOFT)
    l.setStyleSheet(f"background:{bg.name()}; color:{fg.name()}; border-radius: 11px; padding: 2px 10px;")
    l.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return l


def help_mark(tip: str) -> QLabel:
    l = QLabel("?")
    l.setObjectName("Help")
    l.setFont(theme.font(11, True))
    l.setToolTip(tip)
    l.setCursor(Qt.CursorShape.WhatsThisCursor)
    l.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return l


def clear(layout) -> None:
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w is not None:
            w.deleteLater()
        elif it.layout() is not None:
            clear(it.layout())


def row(*widgets, spacing: int = 8, stretch_last: bool = False) -> QHBoxLayout:
    r = QHBoxLayout()
    r.setContentsMargins(0, 0, 0, 0)
    r.setSpacing(spacing)
    for w in widgets:
        if w is None:
            r.addStretch(1)
        elif isinstance(w, QWidget):
            r.addWidget(w)
        else:
            r.addLayout(w)
    if stretch_last:
        r.addStretch(1)
    return r


# ---------------------------------------------------------------- painted widgets

class Ring(QWidget):
    """The big % circle."""

    def __init__(self, value: int, size: int = 96, color: QColor | None = None):
        super().__init__()
        self.value, self.size_px = value, size
        self.color = color or theme.INK
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.size_px * 0.10
        r = QRectF(w / 2 + 1, w / 2 + 1, self.size_px - w - 2, self.size_px - w - 2)
        p.setPen(QPen(QColor("#EEF0E8"), w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        p.drawArc(r, 0, 360 * 16)
        p.setPen(QPen(self.color, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(r, 90 * 16, int(-360 * 16 * max(0, min(100, self.value)) / 100))
        p.setPen(theme.INK)
        p.setFont(theme.font(self.size_px * 0.26, True))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"{self.value}%")


class MiniBars(QWidget):
    """Little bar chart for quarterly numbers; the newest bar is lime, losses are red."""

    def __init__(self, values: list, labels: list[str], height: int = 92):
        super().__init__()
        self.values, self.labels = values, labels
        self.setMinimumHeight(height)
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(240, self.minimumHeight())

    def paintEvent(self, _):
        vals = [v for v in self.values if v is not None]
        if not vals:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self.values)
        W, H = self.width(), self.height()
        lab_h = 16
        top, bottom = 4, H - lab_h
        hi, lo = max(max(vals), 0), min(min(vals), 0)
        span = (hi - lo) or 1
        zero = top + (bottom - top) * hi / span
        gap = 6
        bw = max(4.0, (W - gap * (n - 1)) / n)
        p.setFont(theme.font(10))
        every = 1 if bw >= 34 else 2 if bw >= 16 else 4
        for i, v in enumerate(self.values):
            x = i * (bw + gap)
            if v is not None:
                hgt = (bottom - top) * abs(v) / span
                y = zero - hgt if v >= 0 else zero
                col = theme.BAD if v < 0 else (theme.LIME if i == n - 1 else theme.INK)
                path = QPainterPath()
                path.addRoundedRect(QRectF(x, y, bw, max(hgt, 1.5)), 3, 3)
                p.fillPath(path, col)
            if (n - 1 - i) % every == 0:
                p.setPen(theme.TEXT_FAINT)
                lx = min(max(0.0, x + bw / 2 - 24), W - 48)
                p.drawText(QRectF(lx, bottom + 2, 48, lab_h), Qt.AlignmentFlag.AlignCenter, self.labels[i])


class Avatar(QWidget):
    """Round initials badge with a small green check at the corner (= name came from a real, openable source)."""

    def __init__(self, name: str, checked: bool = True, size: int = 44):
        super().__init__()
        words = [w for w in name.replace(".", " ").split() if w[:1].isalpha()]
        self.text = (words[0][0] + words[-1][0]).upper() if len(words) > 1 else name[:2].upper()
        self.checked, self.d = checked, size
        self.setFixedSize(size + 6, size + 6)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = self.d
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#E2E3DC"))
        p.drawEllipse(QRectF(0, 0, d, d))
        p.setPen(QColor("#444444"))
        p.setFont(theme.font(14, True))
        p.drawText(QRectF(0, 0, d, d), Qt.AlignmentFlag.AlignCenter, self.text)
        if self.checked:
            r = 20
            box = QRectF(d - r + 6, d - r + 6, r, r)
            p.setPen(QPen(theme.SOFT, 2))
            p.setBrush(QColor("#2F9E44"))
            p.drawEllipse(box)
            pen = QPen(QColor("#FFFFFF"), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            c = box.center()
            path = QPainterPath()
            path.moveTo(c.x() - 4, c.y() + 0.5)
            path.lineTo(c.x() - 1, c.y() + 3.5)
            path.lineTo(c.x() + 4, c.y() - 3)
            p.drawPath(path)


class ExposureBars(QWidget):
    """Horizontal bars: [(name, pct, tone)] - how much of the portfolio sits in each bet."""

    def __init__(self, items: list[tuple], row_h: int = 26):
        super().__init__()
        self.items, self.row_h = items, row_h
        self.setMinimumHeight(max(1, len(items)) * row_h)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(300, self.minimumHeight())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        name_w, num_w = 64, 54
        track = QRectF(name_w, 0, max(10, self.width() - name_w - num_w), 10)
        hi = max([max(i[1] for i in self.items), 40]) if self.items else 40
        for k, (name, pct, tone) in enumerate(self.items):
            y = k * self.row_h
            p.setPen(theme.INK)
            p.setFont(theme.font(12, True))
            p.drawText(QRectF(0, y, name_w - 6, self.row_h), Qt.AlignmentFlag.AlignVCenter, name)
            bar_y = y + (self.row_h - 10) / 2
            path = QPainterPath()
            path.addRoundedRect(QRectF(track.x(), bar_y, track.width(), 10), 5, 5)
            p.fillPath(path, QColor("#EEF0E8"))
            w = max(6.0, track.width() * min(pct, hi) / hi)
            fill = QPainterPath()
            fill.addRoundedRect(QRectF(track.x(), bar_y, w, 10), 5, 5)
            p.fillPath(fill, {"good": theme.LIME, "mid": QColor("#F2B84B"), "bad": theme.BAD}.get(tone, theme.INK))
            p.setPen(theme.INK)
            p.setFont(theme.font(12))
            p.drawText(QRectF(self.width() - num_w, y, num_w, self.row_h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{pct:.0f}%")


class PriceLine(QWidget):
    """Last ~6 months of closes, with the floor (support) and ceiling (resistance) as dashed lines."""

    def __init__(self, closes: list[float], support=None, resistance=None, buy_price=None, height: int = 120):
        super().__init__()
        self.closes, self.support, self.resistance, self.buy = closes, support, resistance, buy_price
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _):
        if len(self.closes) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width() - 70, self.height() - 8
        levels = [x for x in (self.support, self.resistance, self.buy) if x]
        hi, lo = max(self.closes + levels), min(self.closes + levels)
        span = (hi - lo) or 1

        def y(v):
            return 4 + H * (hi - v) / span
        path = QPainterPath(QPointF(0, y(self.closes[0])))
        step = W / (len(self.closes) - 1)
        for i, v in enumerate(self.closes[1:], 1):
            path.lineTo(i * step, y(v))
        p.setPen(QPen(theme.INK, 1.8))
        p.drawPath(path)
        p.setFont(theme.font(10))
        for val, col, name in ((self.support, theme.GOOD, "แนวรับ"), (self.resistance, theme.BAD, "แนวต้าน"),
                               (self.buy, theme.MID, "ราคาที่ซื้อ")):
            if not val:
                continue
            p.setPen(QPen(col, 1.2, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(0, y(val)), QPointF(W, y(val)))
            p.setPen(col)
            p.drawText(QRectF(W + 6, y(val) - 9, 64, 18), Qt.AlignmentFlag.AlignVCenter, f"{name} {val:,.0f}")
        p.setBrush(theme.LIME)
        p.setPen(QPen(theme.INK, 1.5))
        p.drawEllipse(QPointF(W, y(self.closes[-1])), 4, 4)


# ---------------------------------------------------------------- background work

class _Signals(QObject):
    done = Signal(object, object)       # result, error
    progress = Signal(str)


class _Job(QRunnable):
    def __init__(self, fn, sig: _Signals):
        super().__init__()
        self.fn, self.sig = fn, sig

    def run(self):
        try:
            res = self.fn(self.sig.progress.emit)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.sig.done.emit(None, e)
            return
        self.sig.done.emit(res, None)


_alive: set = set()


def run_in_background(fn, done, progress=None) -> None:
    """fn(progress_cb) runs on a worker thread; done(result, error) and progress(text) run on the UI thread."""
    sig = _Signals()
    _alive.add(sig)

    def finish(res, err):
        _alive.discard(sig)
        done(res, err)
    sig.done.connect(finish, Qt.ConnectionType.QueuedConnection)
    if progress:
        sig.progress.connect(progress, Qt.ConnectionType.QueuedConnection)
    QThreadPool.globalInstance().start(_Job(fn, sig))
