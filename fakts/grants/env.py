from fakts.grants.errors import GrantError
import os
import logging
from fakts.types import FaktsRequest, FaktValue
from typing import Dict, Any, List
from pydantic import BaseModel

logger = logging.getLogger(__name__)


def nested_set(dic: Dict[str, Any], keys: List[str], value: Any) -> None:
    """Sets a value in a nested dictionary (inplace version)

    Parameters
    ----------
    dic : Dict
        The dictionary to set the value in
    keys : List[str]
        The keys to set the value in
    value : Any
        The value to set
    """
    for key in keys[:-1]:
        dic = dic.setdefault(key, {})
    dic[keys[-1]] = value
    return None


class EnvGrant(BaseModel):
    """Extras a configuration tree from the current environment
    variables.

    It will load all the environment variables that start with the `prepend` string,
    and will parse them as a configuration tree (splitting the key by the `delimiter`)
    it will also convert the keys to lowercase.

     E.g.

        ```env
        FAKTS_GROUP_NAME__KEY_NAME=value
        FAKTS_OTHER__KEY_NAME2=value2
        ```
        ```python

        grant = EnvGrant(delimiter__="__", prepend="FAKTS_") # the default values

        with Fakts(grant=grants) as fakts:
            config = grant.get() # accessing the config
            print(config["group_name"]["key_name"]) # value

            print(grant.get("other.key_name2") # value2
        ```
        ```

    """

    prepend: str = "FAKTS_"
    delimiter: str = "__"

    async def aload(self, request: FaktsRequest) -> Dict[str, FaktValue]:
        """Loads the configuration from the environment variables.

        It will load all the environment variables that start with the `prepend` string,
        and will parse them as a configuration tree (splitting the key by the `delimiter`)

        E.g.

        ```env
        FAKTS_GROUP_NAME__KEY_NAME=value
        FAKTS_OTHER__KEY_NAME2=value2
        ```
        ```python

        grant = EnvGrant(delimiter__="__", prepend="FAKTS_") # the default values

        with Fakts(grant=grants) as fakts:
            config = grant.get() # accessing the config
            print(config["group_name"]["key_name"]) # value

            print(grant.get("other.key_name2") # value2
        ```

        Returns
        -------
        Dict[str, FaktValue]
            The loaded fakts

        Raises
        ------
        GrantError
            If the environment variables could not be loaded, because
            of a nested key that is not a dictionary.
        """
        try:
            data: Dict[str, FaktValue] = {}

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
