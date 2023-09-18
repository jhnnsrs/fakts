from fakts.grants.base import FaktsGrant
import yaml
from fakts.types import FaktsRequest


class YamlGrant(FaktsGrant):
    filepath: str

    async def aload(self, request: FaktsRequest):
        with open(self.filepath, "r") as file:
            config = yaml.load(file, Loader=yaml.FullLoader)

        return config
