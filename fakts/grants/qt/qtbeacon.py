from qtpy.QtCore import Signal
from fakts.grants.beacon import BeaconGrant
from fakts.beacon.beacon import FaktsEndpoint
from fakts.grants.base import GrantException
from qtpy import QtWidgets
import asyncio
import logging
from koil.qt import QtCoro, QtFuture

logger = logging.getLogger(__name__)


class RetrieveDialog(QtWidgets.QDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle("Check your Broswer")
        self.button = QtWidgets.QPushButton("Cancel")
        self.layout = QtWidgets.QHBoxLayout()
        self.layout.addWidget(self.button)
        self.setLayout(self.layout)


class SelfScanWidget(QtWidgets.QWidget):
    user_endpoint = Signal(FaktsEndpoint)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.layout = QtWidgets.QHBoxLayout()
        self.lineEdit = QtWidgets.QLineEdit()
        self.addButton = QtWidgets.QPushButton("Scan")

        self.layout.addWidget(self.lineEdit)
        self.layout.addWidget(self.addButton)
        self.addButton.clicked.connect(self.on_add)
        self.setLayout(self.layout)

    def on_add(self):
        host = self.lineEdit.text()
        url = f"http://{host}/setupapp"
        endpoint = FaktsEndpoint(url=url, name="Self Added")
        self.user_endpoint.emit(endpoint)


class UserCancelledException(GrantException):
    pass


class QtSelectableBeaconGrant(BeaconGrant, QtWidgets.QDialog):
    new_endpoint = Signal(FaktsEndpoint)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setWindowTitle("Search Endpoints...")

        self.retrieve_dialog = RetrieveDialog(parent=self)

        self.show_coro = QtCoro(lambda f: self.show(), autoresolve=True)
        self.hide_coro = QtCoro(lambda f: self.hide(), autoresolve=True)

        self.select_endpoint = QtCoro(self.demand_selection_of_endpoint)
        self.select_endpoint_future = None

        self.new_endpoint.connect(self.on_new_endpoint)

        self.endpoints = []

        self.listWidget = QtWidgets.QListWidget()

        self.scanWidget = SelfScanWidget()

        QBtn = QtWidgets.QDialogButtonBox.Cancel
        self.buttonBox = QtWidgets.QDialogButtonBox(QBtn)
        self.buttonBox.rejected.connect(self.on_reject)

        self.layout = QtWidgets.QVBoxLayout()
        self.layout.addWidget(self.listWidget)
        self.layout.addWidget(self.scanWidget)
        self.layout.addWidget(self.buttonBox)
        self.setLayout(self.layout)

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

    def on_new_endpoint(self, config):
        self.listWidget.clear()

        self.endpoints.append(config)

        for endpoint in self.endpoints:
            self.listWidget.addItem(f"{endpoint.name} at {endpoint.url}")

        self.listWidget.itemClicked.connect(self.on_endpoint_clicked)

    async def emit_endpoints(self):
        try:
            async for endpoint in self._discov.ascan_gen():
                self.new_endpoint.emit(endpoint)
        except Exception as e:
            print(e)

    async def aload(self, previous={}, **kwargs):
        loop = asyncio.get_event_loop()
        emitting_task = loop.create_task(self.emit_endpoints())
        try:

            await self.show_coro.acall()
            try:
                endpoint = await self.select_endpoint.acall()

                konfik = await self._retriev.aretrieve(endpoint, previous=previous)

                await self.hide_coro.acall()

            finally:
                emitting_task.cancel()
                try:
                    await emitting_task
                except asyncio.CancelledError as e:
                    logger.info("Cancelled the Discovery task")
        except Exception as e:
            logger.exception(e)
            raise e

        return konfik
