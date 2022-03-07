import asyncio
from koil import Koil
from PyQt5 import QtWidgets, QtCore
from fakts.fakts import Fakts
from fakts.grants.qt.qtbeacon import QtSelectableBeaconGrant
from fakts.grants.qt.qtyamlgrant import QtSelectYaml, QtYamlGrant
from fakts.qt import QtFakts
from koil.qt import QtKoil, QtTask
import os

TESTS_FOLDER = str(os.path.dirname(os.path.abspath(__file__)))


class FaktualBeacon(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.koil = QtKoil()
        self.fakts = Fakts(grants=[QtSelectableBeaconGrant()])
        self.load_fakts_task = QtTask(self.fakts.aload)
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
        self.load_fakts_task.run(force_refresh=True)
        self.greet_label.setText("Loading...")


class FaktualYaml(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.koil = QtKoil()
        self.fakts = Fakts(grants=[QtYamlGrant()])
        self.load_fakts_task = QtTask(self.fakts.aload)
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
        self.load_fakts_task.run(force_refresh=True)
        self.greet_label.setText("Loading...")


def test_no_interference(qtbot, monkeypatch):
    """Tests if just adding koil interferes with normal
    qtpy widgets.

    Args:
        qtbot (_type_): _description_
    """
    widget = FaktualBeacon()
    qtbot.addWidget(widget)

    monkeypatch.setattr(
        QtSelectYaml,
        "ask",
        classmethod(lambda *args, **kwargs: f"{TESTS_FOLDER}/selectable_yaml.yaml"),
    )

    # click in the Greet button and make sure it updates the appropriate label
    with qtbot.waitSignal(widget.load_fakts_task.returned) as b:
        # click in the Greet button and make sure it updates the appropriate label
        qtbot.mouseClick(widget.button_greet, QtCore.Qt.LeftButton)
        assert widget.greet_label.text() == "Loading..."

    assert b.args[0] == "Hello, world!"


def test_no_interference(qtbot, monkeypatch):
    """Tests if just adding koil interferes with normal
    qtpy widgets.

    Args:
        qtbot (_type_): _description_
    """
    widget = FaktualYaml()
    qtbot.addWidget(widget)

    monkeypatch.setattr(
        QtSelectYaml,
        "ask",
        classmethod(lambda *args, **kwargs: f"{TESTS_FOLDER}/selectable_yaml.yaml"),
    )

    with qtbot.waitSignal(widget.load_fakts_task.returned) as b:
        # click in the Greet button and make sure it updates the appropriate label
        qtbot.mouseClick(widget.button_greet, QtCore.Qt.LeftButton)

        assert widget.greet_label.text() == "Loading..."
    assert isinstance(b.args[0], dict)
