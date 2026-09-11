from fakts_next.grants.remote.discovery.advertised import (
    alisten_pure,
    ListenBinding,
    Beacon,
)
from qtpy import QtWidgets, QtCore, QtGui
import asyncio
import logging
from koil.qt import qt_to_async, QtFuture
from fakts_next.grants.remote.discovery.utils import discover_url
from typing import Any, Optional
from typing import Dict, List

from pydantic import Field
from fakts_next.grants.remote.models import FaktsEndpoint, SSLContextModel


logger = logging.getLogger(__name__)


class SelfScanWidget(QtWidgets.QWidget):  # type: ignore
    """A widget that allows the user to scan for beacons

        It has a line edit and a button. When the button is clicked,
        the line edit is scanned for a url, and if it is a valid url,
        a beacon is emitted with the url.
    from .utils import discover_url

        No validation is done on the url, so it is up to the user to
        enter a valid url.

    """

    user_beacon_added = QtCore.Signal(Beacon)  # type: ignore
    """Signal that is emitted when a new beacon is added"""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore
        """Constructor for SelfScanWidget"""
        super().__init__(*args, **kwargs)  # type: ignore
        self.scanlayout = QtWidgets.QHBoxLayout()
        self.lineEdit = QtWidgets.QLineEdit()
        self.addButton = QtWidgets.QPushButton("Scan")

        self.scanlayout.addWidget(self.lineEdit)
        self.scanlayout.addWidget(self.addButton)
        self.addButton.clicked.connect(self.on_add)
        self.setLayout(self.scanlayout)  # type: ignore

    def on_add(self) -> None:
        """Called when the button is clicked"""
        host = self.lineEdit.text()
        beacon = Beacon(url=host)
        self.user_beacon_added.emit(beacon)  # type: ignore


class FaktsEndpointButton(QtWidgets.QPushButton):  # type: ignore
    """A button that represents a FaktsEndpoint

    It has a title and a subtitle, and when clicked, emits
    a signal with the endpoint
    """

    accept_clicked = QtCore.Signal(FaktsEndpoint)  # type: ignore

    def __init__(self, endpoint: FaktsEndpoint, parent: Optional[QtWidgets.QWidget] = None) -> None:
        """Constructor for FaktsEndpointButton"""
        super(FaktsEndpointButton, self).__init__(parent)  # type: ignore
        self.endpoint = endpoint
        self.hovered = False
        self.is_pressed = False
        self.clicked.connect(self.on_clicked)  # type: ignore
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))  # type: ignore  # Default cursor
        self.initUI()

    def initUI(self) -> None:
        """Initialize UI elements"""
        # Set the button's minimum height and other properties if needed
        self.setMinimumHeight(50)  # type: ignore
        self.setContentsMargins(10, 10, 10, 10)  # type: ignore
        self.setToolTip("Connect to " + self.endpoint.name)  # type: ignore

    def paintEvent(self, a0: Any) -> None:
        """Paint the button with the given style, title and subtitle"""
        # Call the superclass paint event to keep the button look normal
        super(FaktsEndpointButton, self).paintEvent(a0)

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)  # type: ignore

        # Calculate the position for the title and subtitle
        title_pos_y = int(self.rect().height() / 3)
        subtitle_pos_y = int(self.rect().height() / 3 * 2)

        # Set the font for the title
        title_font = QtGui.QFont("SansSerif", 12)  # Make the title font a bit bigger
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(
            QtCore.QRect(10, 10, self.width(), title_pos_y),  # type: ignore
            QtCore.Qt.AlignLeft,  # type: ignore
            self.endpoint.name,
        )

        # Set the font for the subtitle
        subtitle_font = QtGui.QFont("SansSerif", 8)
        painter.setFont(subtitle_font)
        painter.drawText(
            QtCore.QRect(10, title_pos_y + 10, self.width(), subtitle_pos_y),  # type: ignore
            QtCore.Qt.AlignLeft,  # type: ignore
            "@" + self.endpoint.base_url,
        )

    def enterEvent(self, a0: Any) -> None:
        """Sets the cursor to pointing hand when hovering over the button"""
        self.hovered = True

        self.update()  # type: ignore # Trigger a repaint
        self.setCursor(  # type: ignore
            QtGui.QCursor(QtCore.Qt.PointingHandCursor)  # type: ignore
        )  # Change cursor to pointer

    def leaveEvent(self, a0: Any) -> None:
        """Sets the cursor to arrow when not hovering over the button"""
        self.hovered = False
        self.setCursor(QtGui.QCursor(QtCore.Qt.ArrowCursor))  # type: ignore  # Change cursor to arrow
        self.update()  # type: ignore# Trigger a repaint# type: ignore

    def mousePressEvent(self, e: Any) -> None:
        """Sets the button to pressed when clicked"""
        self.is_pressed = True
        self.update()  ## type: ignore Trigger a repaint
        super(FaktsEndpointButton, self).mousePressEvent(e)  # type: ignore

    def mouseReleaseEvent(self, e: Any) -> None:
        """Sets the button to not pressed when released"""
        self.is_pressed = False
        self.update()  # type: ignore # Trigger a repaint
        super(FaktsEndpointButton, self).mouseReleaseEvent(e)  # type: ignore

    def on_clicked(self) -> None:
        """Called when the button is clicked"""
        self.accept_clicked.emit(self.endpoint)  # type: ignore


class SelectBeaconWidget(QtWidgets.QDialog):  # type: ignore
    """A widget that allows the user to select a beacon

    It has a list of buttons, each representing a beacon.
    When a button is clicked, a signal is emitted with the beacon
    """

    new_advertised_endpoint = QtCore.Signal(FaktsEndpoint)  # type: ignore
    new_local_endpoint = QtCore.Signal(FaktsEndpoint)  # type: ignore

    def __init__(
        self,
        *args,  # type: ignore
        settings: Optional[QtCore.QSettings] = None,  # type: ignore
        **kwargs,  # type: ignore
    ) -> None:
        """Constructor for SelectBeaconWidget"""
        super().__init__(*args, **kwargs)  # type: ignore
        self.setWindowTitle("Search Endpoints...")
        self.hide_coro = qt_to_async(self.hide_callback)
        self.show_error_coro = qt_to_async(self.show_error)
        self.clear_endpoints_coro = qt_to_async(self.clear_endpoints)
        self.select_endpoint = qt_to_async(self.demand_selection_of_endpoint)  # type: ignore
        self.settings = settings  # type: ignore

        self.select_endpoint_future = None

        self.new_advertised_endpoint.connect(self.on_new_endpoint)  # type: ignore
        self.new_local_endpoint.connect(self.on_new_endpoint)  # type: ignore

        self.endpoints: List[FaktsEndpoint] = []

        self.wlayout = QtWidgets.QVBoxLayout()

        self.endpointLayout = QtWidgets.QVBoxLayout()

        self.scanWidget = SelfScanWidget()

        QBtn = QtWidgets.QDialogButtonBox.Cancel  # type: ignore
        self.buttonBox = QtWidgets.QDialogButtonBox(QBtn)  # type: ignore
        self.buttonBox.rejected.connect(self.on_reject)

        endgroup = QtWidgets.QGroupBox("Select")
        endgroup.setLayout(self.endpointLayout)
        endgroup.setStyleSheet("padding: 10px;")

        self.scan_layout = QtWidgets.QVBoxLayout()
        self.scan_layout.addWidget(self.scanWidget)

        scangroup = QtWidgets.QGroupBox("Or Scan")
        scangroup.setLayout(self.scan_layout)

        self.wlayout.addWidget(endgroup)
        self.wlayout.addWidget(scangroup)
        self.wlayout.addWidget(self.buttonBox)
        self.setLayout(self.wlayout)  # type: ignore

    def hide_callback(self, future: QtFuture[bool]) -> None:  # type: ignore
        self.hide()
        future.resolve(True)  # type: ignore

    def clearLayout(self, layout: QtWidgets.QVBoxLayout) -> None:
        """Clear the layout"""
        while layout.count():
            child = layout.takeAt(0)
            if child is None:
                continue

            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

    def clear_endpoints(self, future: QtFuture[bool]) -> None:
        """Clear the endpoints"""
        self.clearLayout(self.endpointLayout)
        self.endpoints = []
        future.resolve(True)  # type: ignore

    def show_me(self) -> None:
        """A function that shows the widget"""
        self.show()  # type: ignore

    def show_error(self, future: QtFuture[None], error: Exception) -> None:
        """Show an error message

        Parameters
        ----------
        error : Exception
            Display the error message
        """
        self.show()  # type: ignore
        QtWidgets.QMessageBox.critical(self, "Error", str(error))
        future.resolve(None)  # type: ignore

    def demand_selection_of_endpoint(self, future: QtFuture) -> None:  # type: ignore
        """Is called when the user should select an endpoint. I.e. when the demander
        is called programmatically"""
        self.select_endpoint_future = future  # type: ignore
        self.show()  # type: ignore# type: ignore

    def on_endpoint_clicked(self, item: FaktsEndpoint) -> None:
        """Called when an endpoint button is clicked

        Will resolve the future with the endpoint



        """
        if self.select_endpoint_future:  # type: ignore
            self.select_endpoint_future.resolve(item)  # type: ignore

    def on_reject(self) -> None:
        """Called when the user rejects the dialog

        Will reject the future"""
        if self.select_endpoint_future:  # type: ignore
            self.select_endpoint_future.reject(  # type: ignore
                Exception("User cancelled the this Grant without selecting a Beacon")
            )  # type: ignore
        self.reject()  # type: ignore

    def closeEvent(self, a0: Any) -> None:
        """Called when the window is closed. Will automatically reject the future"""
        if self.select_endpoint_future:  # type: ignore
            self.select_endpoint_future.reject(  # type: ignore
                Exception("User cancelled the this Grant without selecting a Beacon")
            )  # type: ignore

        a0.accept()  # let the window close

    def on_new_endpoint(self, config: FaktsEndpoint) -> None:
        """A callback that is called when a new endpoint is discovered

        Creates a button for the endpoint and adds it to the layout


        """
        self.clearLayout(self.endpointLayout)

        self.endpoints.append(config)

        for endpoint in self.endpoints:
            widget = FaktsEndpointButton(endpoint)

            self.endpointLayout.addWidget(widget)
            widget.accept_clicked.connect(self.on_endpoint_clicked)  # type: ignore


async def wait_first(*tasks) -> Any:  # type: ignore
    """Return the result of first async task to complete with a non-null result"""
    # Get first completed task(s)
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)  # type: ignore

    # Cancel pending tasks
    for task in pending:  # type: ignore
        task.cancel()  # type: ignore

    # Wait for pending tasks to be cancelled
    await asyncio.gather(*pending, return_exceptions=True)  # type: ignore

    # Return first completed task result
    for task in done:  # type: ignore
        return task.result()  # type: ignore


class QtSelectableDiscovery(SSLContextModel):
    """A QT based discovery that will cause the user to select an endpoint
    from a list of network discovered endpoints, as well as endpoints
    that the user manually enters.
    """

    binding: ListenBinding = Field(default_factory=ListenBinding)
    """The address to bind to"""
    strict: bool = False
    """Should we error on bad Beacons"""
    discovered_endpoints: Dict[str, FaktsEndpoint] = Field(default_factory=dict)
    """A cache of discovered endpoints"""
    allow_appending_slash: bool = Field(
        default=True,
        description="If the url does not end with a slash, should we append one? ",
    )
    auto_protocols: List[str] = Field(
        default_factory=lambda: [],
        description="If no protocol is specified, we will try to connect to the following protocols",
    )
    timeout: int = Field(
        default=3,
        description="The timeout for the connection",
    )
    additional_beacons: List[str] = Field(default_factory=lambda: ["localhost:11000", "localhost:11001", "localhost:8000"])
    widget: SelectBeaconWidget

    async def emit_endpoints(self) -> None:
        """A long running task that will emit endpoints that are discovered
        through the network and emit them to be displayed in the widget.
        """
        if self.additional_beacons:
            for i in self.additional_beacons:
                try:
                    endpoint = await discover_url(
                        i,
                        self.ssl_context,
                        auto_protocols=self.auto_protocols,
                        allow_appending_slash=self.allow_appending_slash,
                        timeout=self.timeout,
                    )
                    self.widget.new_local_endpoint.emit(endpoint)  # type: ignore
                except Exception as e:
                    logger.info(f"Could not connect to localhost: {e}")

        try:
            try:
                binding = self.binding
                async for beacon in alisten_pure(binding, strict=self.strict):
                    try:
                        if beacon.url in self.additional_beacons:
                            # we already did this one
                            continue
                        endpoint = await discover_url(
                            beacon.url,
                            self.ssl_context,
                            auto_protocols=self.auto_protocols,
                            allow_appending_slash=self.allow_appending_slash,
                            timeout=self.timeout,
                        )
                        self.widget.new_advertised_endpoint.emit(endpoint)  # type: ignore
                    except Exception as e:
                        logger.info(f"Could not connect to beacon: {beacon.url} {e}")
            except Exception:
                logger.exception("Error in discovery")
                return None

        except Exception as e:
            logger.exception(e)
            raise e

    async def await_user_definition(
        self,
    ) -> Optional[FaktsEndpoint]:
        """Await the user to define a beacon. This will cause the widget to listen for
        user input.

        Returns
        -------
        FaktsEndpoint
            The endpoint that the user defined

        """

        async for beacon in self.widget.beacon_user.aiterate():  # type: ignore
            try:
                return await discover_url(
                    beacon.url,  # type: ignore
                    self.ssl_context,
                    auto_protocols=self.auto_protocols,
                    allow_appending_slash=self.allow_appending_slash,
                    timeout=self.timeout,
                )
            except Exception as e:
                await self.widget.show_error_coro.acall(e)  # type: ignore
                logger.error(f"Could not connect to beacon: {beacon.url} {e}")  # type: ignore
                continue

        return None

    async def adiscover(self) -> FaktsEndpoint:
        """Discover the endpoint

        This discovery will cause the attached widget to be shown, and
        then the user is able to select and endpoint that is discovered
        automatically or by the user.

        Parameters
        ----------
        request : FaktsRequest
            The request to use for the discovery process (is not used)

        Returns
        -------
        FaktsEndpoint
            A valid endpoint
        """

        emitting_task = asyncio.create_task(self.emit_endpoints())
        try:
            await self.widget.clear_endpoints_coro.acall()

            try:
                select_endpoint_task = asyncio.create_task(  # type: ignore
                    self.widget.select_endpoint.acall()  # type: ignore
                )
                user_definition_task = asyncio.create_task(self.await_user_definition())

                endpoint: FaktsEndpoint = await wait_first(select_endpoint_task, user_definition_task)

                await self.widget.hide_coro.acall()  # type: ignore

            finally:
                emitting_task.cancel()
                try:
                    await emitting_task
                except asyncio.CancelledError:
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
