import json
from typing import runtime_checkable, Protocol
from herre.grants.stored_login import (
    UserStore,
    StoredUser,
)
from qtpy import QtWidgets, QtCore
from koil.qt import qt_to_async
import token
from fakts.grants.remote.demanders.types import Token
from fakts.grants.remote.types import FaktsEndpoint


class ShouldWeSaveThisAsDefault(QtWidgets.QDialog):
    def __init__(self, endpoint: FaktsEndpoint, token: Token, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setWindowTitle(f"Connected to {endpoint.name}")

        self.qlabel = QtWidgets.QLabel(
            f"Do you want to auto save this configuration for this endpoint?"
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

        hlayout.addWidget(self.yes_button)
        hlayout.addWidget(self.no_button)

    def on_yes(self):
        self.accept()

    def on_no(self):
        self.reject()


class AutoSaveTokenWidget(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.ashould_we = qt_to_async(self.should_we, autoresolve=True)

    def should_we(self, endpoint: FaktsEndpoint, token: Token) -> bool:
        dialog = ShouldWeSaveThisAsDefault(endpoint, token, parent=self)
        dialog.exec_()
        return dialog.result() == QtWidgets.QDialog.Accepted

    async def ashould_we_save(self, endpoint: FaktsEndpoint, token: Token) -> bool:
        """Should ask the user if we should save the user"""
        return await self.ashould_we(endpoint, token)
