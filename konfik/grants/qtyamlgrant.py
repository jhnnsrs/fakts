

from konfik.grants.base import GrantException, KonfigGrant
import yaml
from koil.qt import FutureWrapper
from qtpy import QtWidgets


class NoFileSelected(GrantException):
    pass

class QtYamlGrant(KonfigGrant, QtWidgets.QWidget):

    def __init__(self, filepath) -> None:
        super().__init__()
        self.frequest = FutureWrapper()
        self.frequest.call.connect(self.on_open_filepath)


    def on_open_filepath(self, ref):
        self.show()
        filepath, weird =  QtWidgets.QFileDialog.getOpenFileName(self, 'Hey! Select a File')
        if filepath:
            self.frequest.resolve.emit(ref, filepath)
        else:
            self.frequest.reject.emit(ref, NoFileSelected("User did not select a File"))

        self.hide()


    async def aload(self, **kwargs):

        filepath = await self.frequest.acall()
        print(filepath)
        with open(filepath,"r") as file:
            config = yaml.load(file, Loader=yaml.FullLoader)

        return config
