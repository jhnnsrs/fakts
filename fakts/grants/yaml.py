from fakts.grants.base import FaktsGrant
import yaml


class YamlGrant(FaktsGrant):
    filepath: str = "random.yaml"

    async def aload(self, previous={}, **kwargs):
        with open(self.filepath, "r") as file:
            config = yaml.load(file, Loader=yaml.FullLoader)

        return config
