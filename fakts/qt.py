from fakts import Fakts
from qtpy import QtCore, QtWidgets
from koil.qt import QtFuture, QtCoro


class QtFakts(QtWidgets.QWidget, Fakts):
    loaded_signal = QtCore.Signal()
    deleted_signal = QtCore.Signal()
    error_signal = QtCore.Signal(Exception)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.layout = QtWidgets.QVBoxLayout()
        self.setWindowTitle("Retrieval Wizard")

        self.show_coro = QtCoro(self.handle_show)
        self.hide_coro = QtCoro(self.handle_hide)

        self.title = QtWidgets.QLabel("Konfig Wizard")
        self.title.setAlignment(QtCore.Qt.AlignCenter)
        self.layout.addWidget(self.title)
        self.subtitle = QtWidgets.QLabel("These are the grants we are able to use")
        self.layout.addWidget(self.subtitle)

        for grant in self.grants:
            grant_title = QtWidgets.QLabel(grant.__class__.__name__)
            self.layout.addWidget(grant_title)

        QBtn = QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        self.buttonBox = QtWidgets.QDialogButtonBox(QBtn)
        self.buttonBox.accepted.connect(self.on_start)
        self.buttonBox.rejected.connect(self.on_reject)

        self.layout.addWidget(self.buttonBox)
        self.setLayout(self.layout)

    def handle_show(self, future: QtFuture):
        self.show()
        self.opening_future = future

    def handle_hide(self, future: QtFuture):
        self.close()
        future.resolve()

    def on_start(self):
        self.opening_future.resolve()
        self.accept()

    def on_reject(self):
        self.opening_future.reject(Exception("User denied login"))
        self.reject()

    async def aload(self, *args, **kwargs):
        await self.show_coro.acall()  # await user starts
        try:
            nana = await super().aload()
            self.loaded_signal.emit()
            await self.hide_coro.acall()
            return nana
        except Exception as e:
            self.error_signal.emit(e)
            await self.hide_coro.acall()
            raise e

    async def adelete(self):
        nana = await super().adelete()
        self.deleted_signal.emit()
        return nana
