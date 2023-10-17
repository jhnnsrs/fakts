from herre.grants.stored_login import (
    StoredUser,
)
from qtpy import QtWidgets
from fakts.grants.remote.types import FaktsEndpoint
from koil.qt import qt_to_async


class ShouldWeSaveThisAsDefault(QtWidgets.QDialog):
    def __init__(self, stored: FaktsEndpoint = None, *args, **kwargs) -> None:
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

        self.yes_button.clicked.connect(self.on_yes)
        self.no_button.clicked.connect(self.on_no)

        self.stored = stored

        hlayout.addWidget(self.yes_button)
        hlayout.addWidget(self.no_button)

    def on_yes(self):
        self.accept()

    def on_no(self):
        self.reject()


class AutoSaveEndpointWidget(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.ashould_we = qt_to_async(self.should_we, autoresolve=True)

    def should_we(self, stored: StoredUser) -> bool:
        dialog = ShouldWeSaveThisAsDefault(stored, parent=self)
        dialog.exec_()
        return dialog.result() == QtWidgets.QDialog.Accepted

    async def ashould_we_save(self, store: StoredUser) -> bool:
        """Should ask the user if we should save the user"""
        return await self.ashould_we(store)
