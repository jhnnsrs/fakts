import os

import pytest
from fakts.discovery.base import FaktsEndpoint
from fakts.fakts import Fakts
from fakts.grants.io.qt.yaml import QtYamlGrant, WrappingWidget, QtSelectYaml
from fakts.grants.remote import RetrieveGrant
from fakts.discovery.qt.selectable_beacon import (
    SelectBeaconWidget,
    QtSelectableDiscovery,
)
import uuid
from koil.qt import QtKoil, QtRunner
from PyQt5 import QtCore, QtWidgets

TESTS_FOLDER = str(os.path.dirname(os.path.abspath(__file__)))


class FaktualBeacon(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.koil = QtKoil(parent=self)
        self.koil.enter()

        self.fakts = Fakts(
            grant=RetrieveGrant(
                discovery=QtSelectableDiscovery(widget=SelectBeaconWidget(parent=self)),
                redirect_uri="http://localhost:5000",
                version="v1",
                identifier="faktual",
            ),
        )

        self.load_fakts_task = QtRunner(self.fakts.aload)
        self.load_fakts_task.errored.connect(
            lambda x: self.greet_label.setText(repr(x))
        )
        self.load_fakts_task.returned.connect(
            lambda x: self.greet_label.setText(repr(x))
        )

        self.button_greet = QtWidgets.QPushButton("Greet")
        self.greet_label = QtWidgets.QLabel("")

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.button_greet)
        layout.addWidget(self.greet_label)

        self.setLayout(layout)

        self.button_greet.clicked.connect(self.greet)

    def greet(self):
        self.load_fakts_task.run()
        self.greet_label.setText("Loading...")


class FaktualYaml(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.koil = QtKoil(parent=self)
        self.koil.enter()

        self.fakts = Fakts(
            grant=QtYamlGrant(widget=WrappingWidget(parent=self)),
        )
        self.load_fakts_task = QtRunner(self.fakts.aload)
        self.load_fakts_task.errored.connect(
            lambda x: self.greet_label.setText(repr(x))
        )
        self.load_fakts_task.returned.connect(
            lambda x: self.greet_label.setText(repr(x))
        )

        self.button_greet = QtWidgets.QPushButton("Greet")
        self.greet_label = QtWidgets.QLabel("")

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.button_greet)
        layout.addWidget(self.greet_label)

        self.setLayout(layout)

        self.button_greet.clicked.connect(self.greet)

    def greet(self):
        self.load_fakts_task.run()
        self.greet_label.setText("Loading...")


async def mock_aclaim(self, *args, **kwargs):
    return {
        "hello": "world",
    }


async def mock_ademand(self, *args, **kwargs):
    """Mock ademenad

    Returns a fake token for testing purposes"""
    print("RUn")
    return uuid.uuid4().hex


@pytest.mark.qt
def test_faktual_beacon(qtbot, monkeypatch):
    """Tests if just adding koil interferes with normal
    qtpy widgets.

    Args:
        qtbot (_type_): _description_
    """

    monkeypatch.setattr(
        SelectBeaconWidget,
        "demand_selection_of_endpoint",
        lambda self, f: f.resolve(
            FaktsEndpoint(base_url="http://localhost:5000", name="v1")
        ),
    )

    monkeypatch.setattr(
        RetrieveGrant,
        "ademand",
        mock_ademand,
    )

    monkeypatch.setattr(
        RetrieveGrant,
        "aclaim",
        mock_aclaim,
    )

    widget = FaktualBeacon()
    qtbot.addWidget(widget)

    # click in the Greet button and make sure it updates the appropriate label
    with qtbot.waitSignal(widget.load_fakts_task.returned) as b:
        # click in the Greet button and make sure it updates the appropriate label
        qtbot.mouseClick(widget.button_greet, QtCore.Qt.LeftButton)
        assert widget.greet_label.text() == "Loading..."

    assert isinstance(b.args[0], dict), "Needs to be dict"


@pytest.mark.qt
def test_faktual_yaml(qtbot, monkeypatch):
    """Tests if just adding koil interferes with normal
    qtpy widgets.

    Args:
        qtbot (_type_): _description_
    """

    monkeypatch.setattr(
        QtSelectYaml,
        "ask",
        classmethod(lambda *args, **kwargs: f"{TESTS_FOLDER}/test.yaml"),
    )

    widget = FaktualYaml()
    qtbot.addWidget(widget)

    with qtbot.waitSignal(widget.load_fakts_task.returned) as b:
        # click in the Greet button and make sure it updates the appropriate label
        qtbot.mouseClick(widget.button_greet, QtCore.Qt.LeftButton)

        assert widget.greet_label.text() == "Loading..."

    assert isinstance(b.args[0], dict), "Needs to be dict"
