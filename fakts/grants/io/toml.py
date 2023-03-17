try:
    import tomllib as toml
except ImportError:
    try:
        import toml
    except ImportError:
        raise ImportError(
            "You need to install the `toml` package to use the toml grant."\
            "Or use python 3.11 and higher which comes with the `tomllib` package"
        )
from fakts.grants.base import FaktsGrant


class TomlGrant(FaktsGrant):
    filepath: str

    async def aload(self, force_refresh=False, **kwargs):
        with open(self.filepath, "r") as file:
            config = toml.load(file)

        return config
