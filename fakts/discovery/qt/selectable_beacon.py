from fakts.discovery.errors import DiscoveryError
from pydantic import Field
from qtpy.QtCore import Signal
from typing import List
from fakts.discovery.advertised import AdvertisedDiscovery, alisten_pure, ListenBinding
from fakts.discovery.base import FaktsEndpoint, Beacon
from qtpy import QtWidgets, QtCore, QtGui
import asyncio
import logging
from koil.qt import QtCoro, QtFuture, QtSignal
import ssl
import certifi
import aiohttp
from fakts.discovery.utils import discover_url
from koil import unkoil
logger = logging.getLogger(__name__)


class SelfScanWidget(QtWidgets.QWidget):
    user_beacon_added = Signal(Beacon)

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
        beacon = Beacon(url=host)
        self.user_beacon_added.emit(beacon)


class FaktsEndpointWidget(QtWidgets.QWidget):

    accept_clicked = QtCore.Signal(FaktsEndpoint)

    def __init__(self, endpoint: FaktsEndpoint, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.endpoint = endpoint

        self.user_label = QtWidgets.QLabel(endpoint.name)
        self.user_label.setStyleSheet("font-size: 20px;")
        self.endpoint_label = QtWidgets.QLabel(endpoint.base_url)
        self.endpoint_label.setStyleSheet("font-size: 10px;")
        self.user_label.mousePressEvent = self.on_clicked

        self.hlayout = QtWidgets.QVBoxLayout()
        self.setLayout(self.hlayout)
        self.hlayout.addWidget(self.user_label)
        self.hlayout.addWidget(self.endpoint_label)

    def on_clicked(self, event):
        self.accept_clicked.emit(self.endpoint)




class SelectBeaconWidget(QtWidgets.QDialog):
    new_advertised_endpoint = Signal(FaktsEndpoint)
    new_local_endpoint = Signal(FaktsEndpoint)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setWindowTitle("Search Endpoints...")
        self.show_coro = QtCoro(self.show_me, autoresolve=True)
        self.hide_coro = QtCoro(self.hide, autoresolve=True)
        self.show_error_coro = QtCoro(self.show_error, autoresolve=True)
        self.clear_endpoints_coro = QtCoro(self.clear_endpoints, autoresolve=True)
        self.select_endpoint = QtCoro(self.demand_selection_of_endpoint)


        self.select_endpoint_future = None

        self.new_advertised_endpoint.connect(self.on_new_endpoint)
        self.new_local_endpoint.connect(self.on_new_endpoint)

        self.endpoints = []

        self.endpointLayout = QtWidgets.QVBoxLayout()

        self.scanWidget = SelfScanWidget()
        self.beacon_user = QtSignal(self.scanWidget.user_beacon_added)

        QBtn = QtWidgets.QDialogButtonBox.Cancel
        self.buttonBox = QtWidgets.QDialogButtonBox(QBtn)
        self.buttonBox.rejected.connect(self.on_reject)

        self.wlayout = QtWidgets.QVBoxLayout()
        self.wlayout.addLayout(self.endpointLayout)
        self.wlayout.addWidget(self.scanWidget)
        self.wlayout.addWidget(self.buttonBox)
        self.setLayout(self.wlayout)

    def clearLayout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def clear_endpoints(self):
        self.clearLayout(self.endpointLayout)
        self.endpoints = []

    def show_me(self):
        self.show()

    def show_error(self, error):
        self.show()
        QtWidgets.QMessageBox.critical(self, "Error", str(error))

    def demand_selection_of_endpoint(self, future: QtFuture):
        self.select_endpoint_future = future

    def on_endpoint_clicked(self, item: FaktsEndpoint):
        self.select_endpoint_future.resolve(item)

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
        self.clearLayout(self.endpointLayout)

        self.endpoints.append(config)

        for endpoint in self.endpoints:
            widget = FaktsEndpointWidget(endpoint)
        
            self.endpointLayout.addWidget(widget)
            widget.accept_clicked.connect(self.on_endpoint_clicked)


async def wait_first(*tasks):
    """Return the result of first async task to complete with a non-null result"""
    # Get first completed task(s)
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    # Tasks MAY complete at same time e.g. in unit tests :)
    # Coalesce the first result if present
    for task in done:
        exception = task.exception()
        if exception is None:
            result = task.result()
            if result is not None:
                break
        else:
            result = None
        
    # Gather remaining tasks without raising exceptions
    gather = asyncio.gather(*pending, return_exceptions=True)

    # Cancel remaining tasks if result is non-null otherwise await next pending tasks
    if result:
        gather.cancel()
    elif pending:
        result = await wait_first(*pending)
    
    # Await remaining tasks to ensure they are cancelled
    try:
        await gather
    except asyncio.CancelledError:
        pass
    
    # Return result or raise last exception if no result was returned
    if exception and result is None:
        raise exception
    else:
        return result

class QtSelectableDiscovery(AdvertisedDiscovery):
    widget: SelectBeaconWidget = Field(default_factory=SelectBeaconWidget, exclude=True)
    scan_localhost: bool = True


    async def emit_endpoints(self):

        if self.scan_localhost:
            try:
                localhost_url = "localhost:8000"
                endpoint = await discover_url(localhost_url, self.ssl_context, auto_protocols=self.auto_protocols, allow_appending_slash=self.allow_appending_slash, timeout=self.timeout)
                self.widget.new_local_endpoint.emit(endpoint)
            except Exception as e:
                logger.info(f"Could not connect to localhost: {e}")

        try:
            try:
                binding = ListenBinding(address=self.bind, port=self.broadcast_port, magic_phrase=self.magic_phrase)
                async for beacon in alisten_pure(binding, strict=self.strict):
                    try:
                        if beacon.url == "localhost:8000" and self.scan_localhost:
                            # we already did this one
                            continue
                        endpoint = await discover_url(beacon.url, self.ssl_context, auto_protocols=self.auto_protocols, allow_appending_slash=self.allow_appending_slash, timeout=self.timeout)
                        self.widget.new_advertised_endpoint.emit(endpoint)
                    except Exception as e:
                        logger.info(f"Could not connect to beacon: {beacon.url} {e}")
            except Exception as e:
                logger.exception("Error in discovery")
                return None



                
        except Exception as e:
            logger.exception(e)
            raise e
        

    async def await_user_definition(self,):
        async for beacon in self.widget.beacon_user.aiterate():
            try:
                return await discover_url(beacon.url, self.ssl_context, auto_protocols=self.auto_protocols, allow_appending_slash=self.allow_appending_slash, timeout=self.timeout)
            except Exception as e:
                await self.widget.show_error_coro.acall(e)
                logger.error(f"Could not connect to beacon: {beacon.url} {e}")
                continue

    async def discover(self, force_refresh=False, **kwargs):
        emitting_task = asyncio.create_task(self.emit_endpoints())
        try:
            await self.widget.clear_endpoints_coro.acall()
            await self.widget.show_coro.acall()

            try:
                select_endpoint_task = asyncio.create_task(self.widget.select_endpoint.acall())
                user_definition_task = asyncio.create_task(self.await_user_definition())


                endpoint = await wait_first(select_endpoint_task, user_definition_task)
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
