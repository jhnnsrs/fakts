

from konfik.grants.base import KonfigGrant
import yaml


class YamlGrant(KonfigGrant):

    def __init__(self, filepath) -> None:
        super().__init__()
        self.filepath = filepath



    async def aload(self, **kwargs):
        with open(self.filepath,"r") as file:
            config = yaml.load(file, Loader=yaml.FullLoader)

        return config
