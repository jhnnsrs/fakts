from fakts.grants.base import GrantException, FaktsGrant
import yaml
from koil.qt import QtCoro
from qtpy import QtWidgets


class NoFileSelected(GrantException):
    pass


class QtSelectYaml(QtWidgets.QFileDialog):
    @classmethod
    def ask(cls, text, parent=None):
        filepath, weird = cls.getOpenFileName(parent=parent, caption=text)
        return filepath


class QtYamlGrant(FaktsGrant, QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.get_file_coro = QtCoro(self.on_open_filepath, autoresolve=True)

    def on_open_filepath(self, ref):
        filepath = QtSelectYaml.ask("Select a Yaml", parent=self)
        return filepath

    async def aload(self, previous={}, **kwargs):
        print("Here?")
        filepath = await self.get_file_coro.acall()
        print(filepath)
        with open(filepath, "r") as file:
            config = yaml.load(file, Loader=yaml.FullLoader)

        print("Config")
        print(config)
        return config
