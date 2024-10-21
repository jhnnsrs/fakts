import yaml
from fakts.models import FaktsRequest, FaktValue
from typing import Dict
from pydantic import BaseModel, ConfigDict


class YamlGrant(BaseModel):
    """
    Represent a Grant that loads configuration from a YAML file.

    Attributes
    ----------
    filepath : str
        The path of the YAML file.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    filepath: str

    async def aload(self, request: FaktsRequest) -> Dict[str, FaktValue]:
        """Loads the YAML file and returns the configuration."""
        with open(self.filepath, "r") as file:
            config = yaml.load(file, Loader=yaml.FullLoader)  # type: ignore #TODO: Check why this is not working

        return config
