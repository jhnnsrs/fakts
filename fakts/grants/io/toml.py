from fakts.grants.base import FaktsGrant
import toml


class TomlGrant(FaktsGrant):
    filepath: str

    async def aload(self, force_refresh=False, **kwargs):
        with open(self.filepath, "r") as file:
            config = toml.load(file)

        return config
