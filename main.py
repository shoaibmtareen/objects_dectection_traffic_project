"""Vehicle Analytics System — desktop application entry point.

    python main.py
"""
import sys
import warnings

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from ui import theme

warnings.filterwarnings("ignore", category=FutureWarning)


def make_splash() -> QSplashScreen:
    pix = QPixmap(480, 200)
    pix.fill(QColor(theme.NAVY))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    grad = QLinearGradient(32, 62, 78, 108)
    grad.setColorAt(0, QColor(theme.ACCENT_2))
    grad.setColorAt(1, QColor(theme.ACCENT))
    p.setBrush(grad)
    p.drawRoundedRect(32, 62, 46, 46, 9, 9)
    p.setPen(QColor("#FFFFFF"))
    p.setFont(QFont(theme.FONT_FAMILY, 14, QFont.Weight.ExtraBold))
    p.drawText(32, 62, 46, 46, Qt.AlignmentFlag.AlignCenter, "VA")
    p.setFont(QFont(theme.FONT_FAMILY, 17, QFont.Weight.Bold))
    p.drawText(96, 84, "Vehicle Analytics System")
    p.setPen(QColor(255, 255, 255, 160))
    p.setFont(QFont(theme.FONT_FAMILY, 10))
    p.drawText(96, 106, "Detection · Classification · Tracking · Counting")
    p.end()
    return QSplashScreen(pix)


def main() -> int:
    from utils.helpers import load_settings
    settings = load_settings()
    theme.apply(settings.get("ui", {}).get("theme"))
    settings["colors"] = dict(theme.CLASS_COLORS)  # class colours validated for this theme

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Vehicle Analytics")
    app.setFont(QFont(theme.FONT_FAMILY, 10))
    app.setStyle("Fusion")
    app.setStyleSheet(theme.load_stylesheet())

    splash = make_splash()
    splash.show()
    splash.showMessage("Loading detection model…",
                       Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, QColor(255, 255, 255, 160))
    app.processEvents()

    # heavy imports after the splash is visible
    from core.pipeline import Pipeline
    from storage.database import Database
    from ui.main_window import MainWindow

    db = Database(settings["storage"]["database"])
    pipeline = Pipeline(settings, db)

    window = MainWindow(settings, db, pipeline)
    window.showMaximized()
    splash.finish(window)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
