from qtpy import QtWidgets
from koil.qt import qt_to_async
from fakts.grants.remote.types import FaktsEndpoint


class ShouldWeSaveDialog(QtWidgets.QDialog):
    """A dialog that asks the user if we should save the token or not"""

    def __init__(self, endpoint: FaktsEndpoint, token: str, *args, **kwargs) -> None:
        """Constructor for ShouldWeSaveDialog"""
        super().__init__(*args, **kwargs)
        self.setWindowTitle(f"Connected to {endpoint.name}")

        self.qlabel = QtWidgets.QLabel(
            "Do you want to auto save this configuration for this endpoint?"
        )

        vlayout = QtWidgets.QVBoxLayout()
        self.setLayout(vlayout)

        vlayout.addWidget(self.qlabel)

        hlayout = QtWidgets.QHBoxLayout()
        vlayout.addLayout(hlayout)

        self.yes_button = QtWidgets.QPushButton("Yes")
        self.no_button = QtWidgets.QPushButton("No")

        self.yes_button.clicked.connect(self._on_yes)
        self.no_button.clicked.connect(self._on_no)

        hlayout.addWidget(self.yes_button)
        hlayout.addWidget(self.no_button)

    def _on_yes(self) -> None:
        self.accept()

    def _on_no(self) -> None:
        self.reject()


class AutoSaveTokenWidget(QtWidgets.QWidget):
    """A simple widget that asks the user if we should save the token or not"""

    def __init__(self, *args, **kwargs) -> None:
        """Constructor for AutoSaveTokenWidget"""
        super().__init__(*args, **kwargs)

        self.ashould_we = qt_to_async(self._should_we, autoresolve=True)

    def _should_we(self, endpoint: FaktsEndpoint, token: str) -> bool:
        dialog = ShouldWeSaveDialog(endpoint, token, parent=self)
        dialog.exec_()
        return dialog.result() == QtWidgets.QDialog.Accepted

    async def ashould_we_save(self, endpoint: FaktsEndpoint, token: str) -> bool:
        """Should ask the user if we should save the user"""
        return await self.ashould_we(endpoint, token)
