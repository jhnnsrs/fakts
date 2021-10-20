from fakts import Fakts
from qtpy import QtCore, QtWidgets
from koil.qt import FutureWrapper


class QtFakts(Fakts, QtWidgets.QWidget):
    loaded_signal = QtCore.Signal(bool)
    error_signal = QtCore.Signal(Exception)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args,  **kwargs)

    
    async def aload(self):
        try:
            nana = await super().aload()
            self.loaded_signal.emit(True)
            return nana
        except Exception as e:
            self.error_signal.emit(e)
            raise e
        


    async def adelete(self):
        nana = await super().adelete()
        self.loaded_signal.emit(False)
        return nana


    
