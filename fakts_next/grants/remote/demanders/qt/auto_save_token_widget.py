from qtpy import QtWidgets
from koil.qt import qt_to_async  # type: ignore
from fakts_next.grants.remote.models import FaktsEndpoint


class ShouldWeSaveDialog(QtWidgets.QDialog):  # type: ignore
    """A dialog that asks the user if we should save the token or not"""

    def __init__(self, endpoint: FaktsEndpoint, token: str, *args, **kwargs) -> None:  # type: ignore
        """Constructor for ShouldWeSaveDialog"""
        super().__init__(*args, **kwargs)  # type: ignore
        self.setWindowTitle(f"Connected to {endpoint.name}")  # type: ignore

        self.qlabel = QtWidgets.QLabel("Do you want to auto save this configuration for this endpoint?")

        vlayout = QtWidgets.QVBoxLayout()
        self.setLayout(vlayout)  # type: ignore

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
        self.accept()  # type: ignore

    def _on_no(self) -> None:
        self.reject()  # type: ignore


class AutoSaveTokenWidget(QtWidgets.QWidget):  # type: ignore
    """A simple widget that asks the user if we should save the token or not"""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore
        """Constructor for AutoSaveTokenWidget"""
        super().__init__(*args, **kwargs)  # type: ignore

        self.ashould_we = qt_to_async(self._should_we, autoresolve=True)  # type: ignore

    def _should_we(self, endpoint: FaktsEndpoint, token: str) -> bool:
        dialog = ShouldWeSaveDialog(endpoint, token, parent=self)
        dialog.exec_()  # type: ignore
        return dialog.result() == QtWidgets.QDialog.Accepted  # type: ignore

    async def ashould_we_save(self, endpoint: FaktsEndpoint, token: str) -> bool:
        """Should ask the user if we should save the user"""
        return await self.ashould_we(endpoint, token)  # type: ignore
