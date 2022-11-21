from pydantic import Field
from fakts.grants.base import FaktsGrant
from fakts.grants.errors import GrantError
import yaml
from koil.qt import QtCoro, QtFuture
from qtpy import QtWidgets


class NoFileSelected(GrantError):
    pass


class QtSelectYaml(QtWidgets.QFileDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        self.setNameFilter("YAML files (*.yaml)")

    @classmethod
    def ask(self, parent=None):
        filepath, weird = self.getOpenFileName(parent=parent, caption="Select a Yaml")
        return filepath


class WrappingWidget(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.get_file_coro = QtCoro(self.open_file)

    def open_file(self, future: QtFuture):
        filepath = QtSelectYaml.ask(parent=self)

        if filepath:
            future.resolve(filepath)
        else:
            future.reject(NoFileSelected("No file selected"))


class QtYamlGrant(FaktsGrant):
    """A grant that allows the user to select a yaml file.
    on the Ui. The yaml file is then loaded and returned as a dict."""

    widget: WrappingWidget = Field(exclude=True)

    async def aload(self, **kwargs):
        filepath = await self.widget.get_file_coro.acall()
        with open(filepath, "r") as file:
            config = yaml.load(file, Loader=yaml.FullLoader)

        return config

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {QtWidgets.QFileDialog: lambda x: x.__class__.__name__}
