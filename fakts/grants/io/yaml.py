from fakts.grants.base import FaktsGrant
import yaml


class YamlGrant(FaktsGrant):
    filepath: str

    async def aload(self, force_refresh=False, **kwargs):
        with open(self.filepath, "r") as file:
            config = yaml.load(file, Loader=yaml.FullLoader)

        return config
