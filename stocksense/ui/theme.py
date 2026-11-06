"""Lime + white + black, like the Dime app. Prompt font bundled in assets/fonts."""
from __future__ import annotations

import os

from PySide6.QtGui import QColor, QFont, QIcon

INK = QColor("#0D0D0D")
LIME = QColor("#C8F53C")
LIME_HOVER = QColor("#B9EA22")
BG = QColor("#FFFFFF")
SOFT = QColor("#F5F6F2")
LINE = QColor("#E8E8E3")
TEXT = QColor("#0D0D0D")
TEXT_SOFT = QColor("#6B6B66")
TEXT_FAINT = QColor("#9A9A94")
GOOD = QColor("#3A8A00")
BAD = QColor("#D63A2A")
MID = QColor("#9A6500")
SIDE = QColor("#0D0D0D")
SIDE_ROW = QColor("#1E1E1E")
SIDE_SOFT = QColor("#9A9A9A")

TONE_FG = {"good": GOOD, "bad": BAD, "mid": MID, "none": TEXT_FAINT}
TONE_BG = {"good": QColor("#EEF8DF"), "bad": QColor("#FCEBE8"), "mid": QColor("#FBF3DF"), "none": SOFT}

FAMILIES = ["Prompt", "Leelawadee UI", "Segoe UI", "Noto Sans Thai", "sans-serif"]
_fonts_loaded = False


def load_fonts() -> None:
    global _fonts_loaded
    if _fonts_loaded:
        return
    from PySide6.QtGui import QFontDatabase
    folder = asset("fonts")
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(folder, name))
    _fonts_loaded = True


def font(px: float, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(FAMILIES)
    f.setPixelSize(max(1, round(px)))
    f.setWeight(QFont.Weight.Medium if bold else QFont.Weight.Normal)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def asset(name: str) -> str:
    from ..paths import resource_dir
    return os.path.join(resource_dir(), "assets", name)


def app_icon() -> QIcon:
    for name in ("stocksense.ico", "stocksense.png"):
        p = asset(name)
        if os.path.exists(p):
            return QIcon(p)
    return QIcon()


def css(c: QColor) -> str:
    return c.name()


STYLE = f"""
* {{ color: {css(TEXT)}; }}
QWidget#Main, QWidget#Right, QWidget#Page, QDialog {{ background: {css(BG)}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QFrame#Side {{ background: {css(SIDE)}; border: none; }}
QFrame#Side QLabel {{ color: #FFFFFF; background: transparent; }}
QFrame#Side QLabel#SideSoft {{ color: {css(SIDE_SOFT)}; }}
QFrame#Card {{ background: {css(BG)}; border: 1px solid {css(LINE)}; border-radius: 12px; }}
QFrame#SoftCard {{ background: {css(SOFT)}; border: none; border-radius: 12px; }}
QFrame#Sep {{ background: {css(LINE)}; border: none; }}
QLabel#Soft {{ color: {css(TEXT_SOFT)}; }}
QLabel#Faint {{ color: {css(TEXT_FAINT)}; }}
QLabel#Help {{ color: {css(TEXT_FAINT)}; border: 1px solid {css(LINE)}; border-radius: 8px; padding: 0px 5px; }}
QLabel#Warn {{ color: {css(MID)}; background: {css(TONE_BG['mid'])}; border-radius: 10px; padding: 10px 12px; }}
QLabel#Danger {{ color: {css(BAD)}; background: {css(TONE_BG['bad'])}; border-radius: 10px; padding: 10px 12px; }}
QLabel#Note {{ color: {css(TEXT_SOFT)}; background: {css(SOFT)}; border-radius: 10px; padding: 10px 12px; }}
QPushButton {{ font-family: Prompt; }}
QPushButton#Lime {{ background: {css(LIME)}; color: {css(INK)}; border: none; border-radius: 10px; padding: 10px 16px; }}
QPushButton#Lime:hover {{ background: {css(LIME_HOVER)}; }}
QPushButton#Lime:disabled, QPushButton#Dark:disabled, QPushButton#Outline:disabled {{ background: {css(SOFT)}; color: {css(TEXT_FAINT)}; border-color: {css(LINE)}; }}
QPushButton#Dark {{ background: {css(INK)}; color: #FFFFFF; border: none; border-radius: 10px; padding: 10px 16px; }}
QPushButton#Dark:hover {{ background: #2A2A2A; }}
QPushButton#Outline {{ background: {css(BG)}; color: {css(INK)}; border: 1px solid {css(INK)}; border-radius: 10px; padding: 9px 16px; }}
QPushButton#Outline:hover {{ background: {css(SOFT)}; }}
QPushButton#Ghost {{ background: transparent; color: {css(TEXT_SOFT)}; border: 1px solid {css(LINE)}; border-radius: 10px; padding: 7px 14px; }}
QPushButton#Ghost:hover {{ color: {css(TEXT)}; border-color: {css(TEXT_FAINT)}; }}
QPushButton#Link {{ background: transparent; border: none; color: {css(TEXT_SOFT)}; padding: 2px; text-align: left; }}
QPushButton#Link:hover {{ color: {css(INK)}; text-decoration: underline; }}
QPushButton#SideAdd {{ background: transparent; color: #CFCFCF; border: 1px dashed #555555; border-radius: 10px; padding: 9px; }}
QPushButton#SideAdd:hover {{ color: #FFFFFF; border-color: {css(LIME)}; }}
QPushButton#SideLink {{ background: transparent; color: {css(SIDE_SOFT)}; border: none; border-radius: 8px; padding: 8px 10px; text-align: left; }}
QPushButton#SideLink:hover {{ color: #FFFFFF; background: {css(SIDE_ROW)}; }}
QFrame#Holding {{ background: transparent; border: 1px solid transparent; border-radius: 10px; }}
QFrame#Holding:hover {{ background: {css(SIDE_ROW)}; }}
QFrame#HoldingOn {{ background: {css(SIDE_ROW)}; border: 1px solid {css(LIME)}; border-radius: 10px; }}
QLineEdit, QDoubleSpinBox, QDateEdit, QPlainTextEdit {{
    background: {css(BG)}; border: 1px solid {css(LINE)}; border-radius: 10px; padding: 9px 12px;
    selection-background-color: {css(LIME)}; selection-color: {css(INK)};
}}
QLineEdit:focus, QDoubleSpinBox:focus, QDateEdit:focus, QPlainTextEdit:focus {{ border-color: {css(INK)}; }}
QDateEdit::drop-down {{ border: none; width: 24px; }}
QToolTip {{ background: {css(INK)}; color: #FFFFFF; border: none; padding: 8px 10px; border-radius: 8px; }}
QListView {{ background: {css(BG)}; border: 1px solid {css(LINE)}; border-radius: 8px; padding: 4px; outline: none; }}
QListView::item {{ padding: 6px 8px; border-radius: 6px; }}
QListView::item:selected, QListView::item:hover {{ background: {css(SOFT)}; color: {css(INK)}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {css(LINE)}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QMessageBox {{ background: {css(BG)}; }}
QMessageBox QPushButton {{ background: {css(INK)}; color: #FFFFFF; border: none; border-radius: 8px; padding: 7px 16px; min-width: 70px; }}
"""
