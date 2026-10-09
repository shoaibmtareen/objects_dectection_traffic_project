from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QLabel, QMainWindow, QMessageBox, QStackedWidget

from core.pipeline import Pipeline
from storage.database import Database
from ui.pages.analytics_page import AnalyticsPage
from ui.pages.records_page import RecordsPage
from ui.pages.source_page import SourcePage


class MainWindow(QMainWindow):
    """Pages: choose a source -> live analytics <-> records & search."""

    def __init__(self, settings: dict, db: Database, pipeline: Pipeline):
        super().__init__()
        self.settings = settings
        self.db = db
        self.pipeline = pipeline
        self.weights = settings["model"]["weights"]

        self.setWindowTitle("Vehicle Analytics System")
        self.resize(1600, 960)
        self.setMinimumSize(1280, 760)

        self.stack = QStackedWidget()
        self.source_page = SourcePage(settings)
        self.analytics_page = AnalyticsPage(settings, db, pipeline)
        self.records_page = RecordsPage(settings, db, self.analytics_page)
        for page in (self.source_page, self.analytics_page, self.records_page):
            self.stack.addWidget(page)
        self.setCentralWidget(self.stack)
        self._records_return = self.source_page

        db_label = QLabel(f"Database: {Path(settings['storage']['database']).name}")
        self.statusBar().addPermanentWidget(db_label)

        self.source_page.start_requested.connect(self.start_analysis)
        self.source_page.view_records.connect(lambda: self.open_records(None, self.source_page))
        self.analytics_page.back_requested.connect(lambda: self.stack.setCurrentWidget(self.source_page))
        self.analytics_page.records_requested.connect(lambda key: self.open_records(key, self.analytics_page))
        self.records_page.back_requested.connect(lambda: self.stack.setCurrentWidget(self._records_return))
        for page in (self.analytics_page, self.records_page):
            page.status_message.connect(self.statusBar().showMessage)

        find = QAction(self)
        find.setShortcut(QKeySequence("Ctrl+F"))
        find.triggered.connect(self._find)
        self.addAction(find)

    def _find(self) -> None:
        if self.stack.currentWidget() is self.records_page:
            self.records_page.search.focus_search()
        elif self.stack.currentWidget() is self.analytics_page:
            self.open_records(None, self.analytics_page)

    def open_records(self, preselect, came_from) -> None:
        self._records_return = came_from
        label = "Back to live view" if came_from is self.analytics_page else "Back"
        self.stack.setCurrentWidget(self.records_page)
        self.records_page.open(preselect, label)

    def start_analysis(self, config: dict) -> None:
        if config["weights"] != self.weights and not self._load_model(config["weights"]):
            return
        self.pipeline.set_confidence(config["conf"])
        self.pipeline.detector.imgsz = config.get("imgsz", self.settings["model"]["imgsz"])
        self.pipeline.set_classes(config["classes"])
        self.stack.setCurrentWidget(self.analytics_page)
        self.analytics_page.start(config)

    def _load_model(self, weights: str) -> bool:
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage(f"Loading {Path(weights).name}… (first use downloads it)")
        QGuiApplication.processEvents()
        try:
            self.pipeline.detector = Pipeline.make_detector(self.settings, weights)
            self.weights = weights
            self.statusBar().clearMessage()
            return True
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Model error", f"Could not load the model:\n{exc}")
            return False
        finally:
            QGuiApplication.restoreOverrideCursor()

    def closeEvent(self, event) -> None:
        self.analytics_page.stop(wait=True)
        self.db.close()
        super().closeEvent(event)
