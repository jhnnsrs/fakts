from fakts.grants.base import FaktsGrant
from fakts.grants.errors import GrantError
import os
import logging


logger = logging.getLogger(__name__)


def nested_set(dic, keys, value):
    for key in keys[:-1]:
        dic = dic.setdefault(key, {})
    dic[keys[-1]] = value


class EnvGrant(FaktsGrant):
    """Extras a configuration tree from the current environment

    Example:
        ```env
        FAKTS__GROUP_NAME__KEY_NAME=value
        ```
        ```python
        grant = EnvGrant()
        config = await grant.load()
        print(config["group_name"]["key_name"]) # value
        ```

    """

    prepend: str = "FAKTS_"
    delimiter: str = "__"

    async def aload(self, **kwargs):
        try:
            data = {}

            for key, value in os.environ.items():
                if self.prepend:
                    if not key.startswith(self.prepend):
                        continue
                    key = key[len(self.prepend) :]

                path = list(map(lambda x: x.lower(), key.split(self.delimiter)))
                nested_set(data, path, value)

            return data

        except Exception as e:
            raise GrantError(f"Could not load from env: {e}") from e
