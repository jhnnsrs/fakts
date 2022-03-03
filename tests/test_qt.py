import asyncio
from koil import Koil
from PyQt5 import QtWidgets, QtCore
from fakts.grants.qt.qtbeacon import QtSelectableBeaconGrant
from fakts.qt import QtFakts


async def sleep_and_resolve():
    await asyncio.sleep(0.1)
    return 1


async def sleep_and_yield(times=5):
    for i in range(times):
        await asyncio.sleep(0.1)
        print(i)
        yield i


class Faktual(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fakts = QtFakts(grants=[QtSelectableBeaconGrant()])

        self.button_greet = QtWidgets.QPushButton("Greet")
        self.greet_label = QtWidgets.QLabel("")

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.button_greet)
        layout.addWidget(self.greet_label)

        self.setLayout(layout)

        self.button_greet.clicked.connect(self.greet)

    def greet(self):
        self.fakts.connect(as_task=True)
        self.fakts.


def test_no_interference(qtbot):
    """Tests if just adding koil interferes with normal
    qtpy widgets.

    Args:
        qtbot (_type_): _description_
    """
    widget = KoiledWidget()
    qtbot.addWidget(widget)

    # click in the Greet button and make sure it updates the appropriate label
    qtbot.mouseClick(widget.button_greet, QtCore.Qt.LeftButton)

    assert widget.greet_label.text() == "Hello!"


def test_call_task(qtbot):
    """Tests if we can call a task from a koil widget."""
    widget = KoiledInterferingWidget()
    qtbot.addWidget(widget)

    # click in the Greet button and make sure it updates the appropriate label
    qtbot.mouseClick(widget.call_task_button, QtCore.Qt.LeftButton)
    with qtbot.waitSignal(widget.task.returned) as b:
        print(b)


def test_call_gen(qtbot):
    """Tests if we can call a task from a koil widget."""
    widget = KoiledInterferingWidget()
    qtbot.addWidget(widget)

    # click in the Greet button and make sure it updates the appropriate label
    qtbot.mouseClick(widget.call_gen_button, QtCore.Qt.LeftButton)
    with qtbot.waitSignal(widget.task.yielded) as b:
        print(b)


def test_call_future(qtbot):
    """Tests if we can call a task from a koil widget."""
    widget = KoiledInterferingFutureWidget()
    qtbot.addWidget(widget)

    # click in the Greet button and make sure it updates the appropriate label
    qtbot.mouseClick(widget.call_task_button, QtCore.Qt.LeftButton)
    with qtbot.waitSignal(widget.task.returned, raising=False, timeout=1):
        pass

    assert widget.task_was_run == True
    assert widget.coroutine_was_run == True
