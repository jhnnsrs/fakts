from PyQt5 import QtWidgets
import sys
from fakts import Fakts
from fakts.grants.qt.qtbeacon import QtSelectableBeaconGrant
from koil.qt import QtKoil, QtTask


class Faktual(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.koil = QtKoil()
        self.fakts = Fakts(grants=[QtSelectableBeaconGrant()])

        self.button_greet = QtWidgets.QPushButton("Greet")
        self.greet_label = QtWidgets.QLabel("")

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.button_greet)
        layout.addWidget(self.greet_label)

        self.setLayout(layout)

        self.button_greet.clicked.connect(self.greet)

    def greet(self):
        task: QtTask = self.fakts.load(force_refresh=True, as_task=True)
        task.errored.connect(lambda x: self.greet_label.setText(repr(x)))
        task.run()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    mw = Faktual()
    mw.show()
    sys.exit(app.exec_())
