from pydantic import Field
from qtpy.QtCore import Signal
from fakts.discovery.advertised import AdvertisedDiscovery
from fakts.discovery.base import FaktsEndpoint
from qtpy import QtWidgets
import asyncio
import logging
from koil.qt import QtCoro, QtFuture


logger = logging.getLogger(__name__)


class SelfScanWidget(QtWidgets.QWidget):
    user_endpoint = Signal(FaktsEndpoint)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.scanlayout = QtWidgets.QHBoxLayout()
        self.lineEdit = QtWidgets.QLineEdit()
        self.addButton = QtWidgets.QPushButton("Scan")

        self.scanlayout.addWidget(self.lineEdit)
        self.scanlayout.addWidget(self.addButton)
        self.addButton.clicked.connect(self.on_add)
        self.setLayout(self.scanlayout)

    def on_add(self):
        host = self.lineEdit.text()
        endpoint = FaktsEndpoint(base_url=host, name="Self Added")
        self.user_endpoint.emit(endpoint)


class SelectBeaconWidget(QtWidgets.QDialog):
    new_endpoint = Signal(FaktsEndpoint)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setWindowTitle("Search Endpoints...")
        self.show_coro = QtCoro(self.show_me)
        self.hide_coro = QtCoro(lambda f: self.hide(), autoresolve=True)

        self.select_endpoint = QtCoro(self.demand_selection_of_endpoint)
        self.select_endpoint_future = None

        self.new_endpoint.connect(self.on_new_endpoint)

        self.endpoints = []

        self.listWidget = QtWidgets.QListWidget()

        self.scanWidget = SelfScanWidget()
        self.scanWidget.user_endpoint.connect(self.on_new_endpoint)

        QBtn = QtWidgets.QDialogButtonBox.Cancel
        self.buttonBox = QtWidgets.QDialogButtonBox(QBtn)
        self.buttonBox.rejected.connect(self.on_reject)

        self.wlayout = QtWidgets.QVBoxLayout()
        self.wlayout.addWidget(self.listWidget)
        self.wlayout.addWidget(self.scanWidget)
        self.wlayout.addWidget(self.buttonBox)
        self.setLayout(self.wlayout)

    def show_me(self, f: QtFuture):
        self.show()
        f.resolve()

    def demand_selection_of_endpoint(self, future: QtFuture):
        self.select_endpoint_future = future

    def on_endpoint_clicked(self, item):
        index = self.listWidget.indexFromItem(item).row()
        self.select_endpoint_future.resolve(self.endpoints[index])

    def on_reject(self):
        if self.select_endpoint_future:
            self.select_endpoint_future.reject(
                Exception("User cancelled the this Grant without selecting a Beacon")
            )
        self.reject()

    def closeEvent(self, event):
        # do stuff
        if self.select_endpoint_future:
            self.select_endpoint_future.reject(
                Exception("User cancelled the this Grant without selecting a Beacon")
            )

        event.accept()  # let the window close

    def on_new_endpoint(self, config: FaktsEndpoint):
        self.listWidget.clear()

        self.endpoints.append(config)

        for endpoint in self.endpoints:
            self.listWidget.addItem(f"{endpoint.name} at {endpoint.base_url}")

        self.listWidget.itemClicked.connect(self.on_endpoint_clicked)


class QtSelectableDiscovery(AdvertisedDiscovery):
    widget: SelectBeaconWidget = Field(default_factory=SelectBeaconWidget, exclude=True)

    async def emit_endpoints(self):
        try:
            async for endpoint in self.astream():
                self.widget.new_endpoint.emit(endpoint)
        except Exception as e:
            logger.exception(e)
            raise e

    async def aget(self):
        emitting_task = asyncio.create_task(self.emit_endpoints())
        try:

            await self.widget.show_coro.acall()
            try:
                endpoint = await self.widget.select_endpoint.acall()
                await self.widget.hide_coro.acall()

            finally:
                emitting_task.cancel()
                try:
                    await emitting_task
                except asyncio.CancelledError as e:
                    logger.info("Cancelled the Discovery task")

            return endpoint
        except Exception as e:
            logger.exception(e)
            emitting_task.cancel()

            try:
                await emitting_task
            except asyncio.CancelledError:
                logger.info("Cancelled the Discovery task")

            raise e

    class Config:
        arbitrary_types_allowed = True
