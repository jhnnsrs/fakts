from koil import Koil
from PyQt5 import QtWidgets, QtCore
from fakts.beacon.beacon import EndpointBeacon, FaktsEndpoint
from fakts.beacon.retriever import FaktsRetriever
from fakts.fakts import Fakts
from fakts.grants.qt.qtbeacon import QtSelectableBeaconGrant, SelectBeaconWidget
from fakts.grants.qt.qtyamlgrant import QtSelectYaml, QtYamlGrant, WrappingWidget
from koil.qt import QtKoil, QtRunner
import os

TESTS_FOLDER = str(os.path.dirname(os.path.abspath(__file__)))


class FaktualBeacon(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.koil = QtKoil(parent=self)
        self.koil.connect()

        self.fakts = Fakts(
            grants=[QtSelectableBeaconGrant(widget=SelectBeaconWidget(parent=self))],
            force_refresh=True,
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.koil = QtKoil(parent=self)
        self.koil.connect()

        self.fakts = Fakts(
            grants=[QtYamlGrant(widget=WrappingWidget(parent=self))], force_refresh=True
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


async def mock_aretrieve(self, *args, **kwargs):
    return {
        "hello": "world",
    }


def test_faktual_beacon(qtbot, monkeypatch):
    """Tests if just adding koil interferes with normal
    qtpy widgets.

    Args:
        qtbot (_type_): _description_
    """

    monkeypatch.setattr(
        SelectBeaconWidget,
        "demand_selection_of_endpoint",
        lambda self, f: f.resolve(FaktsEndpoint),
    )

    monkeypatch.setattr(
        FaktsRetriever,
        "aretrieve",
        mock_aretrieve,
    )

    widget = FaktualBeacon()
    qtbot.addWidget(widget)

    # click in the Greet button and make sure it updates the appropriate label
    with qtbot.waitSignal(widget.load_fakts_task.returned) as b:
        # click in the Greet button and make sure it updates the appropriate label
        qtbot.mouseClick(widget.button_greet, QtCore.Qt.LeftButton)
        assert widget.greet_label.text() == "Loading..."

    assert isinstance(b.args[0], dict), "Needs to be dict"


def test_faktual_yaml(qtbot, monkeypatch):
    """Tests if just adding koil interferes with normal
    qtpy widgets.

    Args:
        qtbot (_type_): _description_
    """

    monkeypatch.setattr(
        QtSelectYaml,
        "ask",
        classmethod(lambda *args, **kwargs: f"{TESTS_FOLDER}/selectable_yaml.yaml"),
    )

    widget = FaktualYaml()
    qtbot.addWidget(widget)

    with qtbot.waitSignal(widget.load_fakts_task.returned) as b:
        # click in the Greet button and make sure it updates the appropriate label
        qtbot.mouseClick(widget.button_greet, QtCore.Qt.LeftButton)

        assert widget.greet_label.text() == "Loading..."

    assert isinstance(b.args[0], dict), "Needs to be dict"
