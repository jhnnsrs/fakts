from PyQt5 import QtWidgets
import sys
from fakts import Fakts
from fakts.grants.cli.clibeacon import CLIBeaconGrant
from koil.qt import QtKoil, QtTask

from fakts.grants.qt.qtyamlgrant import QtYamlGrant


fakts = Fakts(grants=[CLIBeaconGrant()])
fakts.load(force_refresh=True)
