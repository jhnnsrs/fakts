from konfik import Konfik
from qtpy import QtCore, QtWidgets



class QtKonfik(Konfik, QtWidgets.QWidget):
    loaded_signal = QtCore.Signal(bool)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args,  **kwargs)

    
    async def aload(self):
        nana = await super().aload()
        self.loaded_signal.emit(True)
        return nana


    async def adelete(self):
        nana = await super().adelete()
        self.loaded_signal.emit(False)
        return nana


    
