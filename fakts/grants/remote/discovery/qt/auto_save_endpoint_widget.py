from qtpy import QtWidgets
from fakts.grants.remote.types import FaktsEndpoint
from koil.qt import qt_to_async


class ShouldWeSaveThisAsDefault(QtWidgets.QDialog):
    """A dialog that asks the user if we should save the ednpoint or not"""

    def __init__(self, stored: FaktsEndpoint, *args, **kwargs) -> None:
        """Constructor for ShouldWeSaveDialog"""
        super().__init__(*args, **kwargs)
        self.setWindowTitle(f"Connected to {stored.name}")

        self.qlabel = QtWidgets.QLabel(
            "Do you want to save this endpoint as the default endpoint?"
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

        self.stored = stored

        hlayout.addWidget(self.yes_button)
        hlayout.addWidget(self.no_button)

    def _on_yes(self) -> None:
        self.accept()

    def _on_no(self) -> None:
        self.reject()


class AutoSaveEndpointWidget(QtWidgets.QWidget):
    """A simple widget that asks the user if we should save the endoint or not"""

    def __init__(self, *args, **kwargs) -> None:
        """Constructor for AutoSaveEndpointWidget"""
        super().__init__(*args, **kwargs)

        self.ashould_we = qt_to_async(self._should_we, autoresolve=True)

    def _should_we(self, stored: FaktsEndpoint) -> bool:
        dialog = ShouldWeSaveThisAsDefault(stored, parent=self)
        dialog.exec_()
        return dialog.result() == QtWidgets.QDialog.Accepted

    async def ashould_we_save(self, store: FaktsEndpoint) -> bool:
        """Should ask the user if we should save the user"""
        return await self.ashould_we(store)
