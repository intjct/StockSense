"""“มีเวอร์ชันใหม่ · อัปเดตเลย” bar at the top. Never updates by itself — waits for a click."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from .. import VERSION, updater
from . import theme
from .widgets import button, label, run_in_background

RECHECK_MS = 6 * 3600 * 1000


class UpdateBar(QWidget):
    quit_requested = Signal()

    def __init__(self, busy=lambda: False):
        super().__init__()
        self.busy = busy
        self.found: updater.Update | None = None
        self.dismissed = ""
        self._checking = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 8)
        f = QFrame()
        f.setStyleSheet(f"QFrame{{background:{theme.LIME.name()}; border-radius:10px;}}")
        r = QHBoxLayout(f)
        r.setContentsMargins(14, 8, 10, 8)
        self.text = label("", 13, True, color=theme.INK)
        self.later = button("ไว้ทีหลัง", "Link", 12)
        self.later.clicked.connect(self._later)
        self.go = button("อัปเดตเลย", "Dark", 12, True)
        self.go.clicked.connect(self._install)
        r.addWidget(self.text, 1)
        r.addWidget(self.later)
        r.addWidget(self.go)
        outer.addWidget(f)
        self.setVisible(False)
        self._timer = QTimer(self, interval=RECHECK_MS, timeout=lambda: self.check())

    def start(self):
        QTimer.singleShot(4000, self.check)
        self._timer.start()

    def check(self, status_cb=None):
        if self._checking:
            return
        self._checking = True

        def done(res, err):
            self._checking = False
            if err:
                if status_cb:
                    status_cb("เช็กไม่ได้ตอนนี้ ลองใหม่เมื่อต่ออินเทอร์เน็ตอยู่")
                return
            self.found = res
            if res:
                if status_cb:
                    self.dismissed = ""
                    status_cb(f"มีเวอร์ชันใหม่ {res.version} · กด “อัปเดตเลย” ด้านบนได้เลย")
                self._show()
            else:
                self.setVisible(False)
                if status_cb:
                    status_cb(f"ตอนนี้เป็นเวอร์ชันล่าสุดแล้ว ({VERSION}) ✓")
        run_in_background(lambda _p: updater.check(VERSION), done)

    def _show(self):
        u = self.found
        if not u or u.version == self.dismissed:
            return
        self.text.setText(f"มีเวอร์ชันใหม่ {u.version}  ·  ตอนนี้ใช้อยู่ {VERSION}")
        self.text.setToolTip(u.notes)
        self.go.setEnabled(True)
        self.go.setText("อัปเดตเลย")
        self.later.setVisible(True)
        self.setVisible(True)

    def _later(self):
        if self.found:
            self.dismissed = self.found.version
        self.setVisible(False)

    def _install(self):
        u = self.found
        if not u:
            return
        if self.busy():
            self.text.setText("รอให้วิเคราะห์เสร็จก่อน แล้วค่อยกดอัปเดตนะ")
            return
        self.go.setEnabled(False)
        self.go.setText("กำลังโหลด…")
        self.later.setVisible(False)

        def done(path, err):
            if err or not path:
                self.text.setText("โหลดไม่สำเร็จ ลองกด “อัปเดตเลย” อีกครั้ง")
                self.go.setEnabled(True)
                self.go.setText("อัปเดตเลย")
                self.later.setVisible(True)
                return
            try:
                updater.launch_installer(path)
            except OSError:
                self.text.setText("เปิดตัวติดตั้งไม่ได้ ลองอีกครั้ง")
                self.go.setEnabled(True)
                self.go.setText("อัปเดตเลย")
                return
            self.text.setText("กำลังอัปเดต… โปรแกรมจะปิดแล้วเปิดใหม่เอง")
            self.quit_requested.emit()
        run_in_background(lambda _p: updater.download(u), done)
