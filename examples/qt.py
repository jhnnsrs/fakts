from PyQt5 import QtWidgets
import sys
from fakts import Fakts
from koil.qt import QtKoil, QtRunner

from fakts.grants.qt.qtyamlgrant import QtYamlGrant


class Faktual(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.koil = QtKoil(parent=self)
        self.koil.connect()

        self.fakts = Fakts(grants=[QtYamlGrant()], force_refresh=True)

        self.load_fakts_task = QtRunner(self.fakts.aload)
        self.load_fakts_task.errored.connect(
            lambda x: self.greet_label.setText(repr(x))
        )
        self.load_fakts_task.returned.connect(
            lambda x: self.greet_label.setText(repr("Loaded"))
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


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    mw = Faktual()
    mw.show()
    sys.exit(app.exec_())
