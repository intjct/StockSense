"""Starts the window. One copy at a time: opening it again brings the first window forward."""
from __future__ import annotations

import getpass
import sys

from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, VERSION
from .settings import Settings
from .ui import theme

SERVER_NAME = f"stocksense-{getpass.getuser()}"


def _already_running() -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--selftest" in argv:
        from .selftest import selftest
        return selftest()
    qapp = QApplication(argv)
    qapp.setApplicationName(APP_NAME)
    if _already_running():
        return 0
    theme.load_fonts()
    qapp.setFont(theme.font(13))
    qapp.setWindowIcon(theme.app_icon())
    from .ui.mainwindow import MainWindow
    s = Settings.load()
    win = MainWindow(s)

    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def on_conn():
        c = server.nextPendingConnection()
        if c:
            c.readyRead.connect(lambda: (c.readAll(), win.showNormal(), win.raise_(), win.activateWindow()))
    server.newConnection.connect(on_conn)
    win.update_bar.quit_requested.connect(qapp.quit)
    win.show()
    if "--updated" in argv:
        box = QMessageBox(win)
        box.setWindowTitle(APP_NAME)
        box.setText(f"อัปเดตเรียบร้อย ตอนนี้ใช้เวอร์ชัน {VERSION}")
        box.setStyleSheet(theme.STYLE)
        box.show()
    if not s.first_run_done:
        s.first_run_done = True
        s.save()
    return qapp.exec()
