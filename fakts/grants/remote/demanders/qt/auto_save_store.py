import logging
from qtpy import QtCore

from fakts.grants.remote.types import FaktsEndpoint

logger = logging.getLogger(__name__)
from typing import Dict, Optional

import json
from pydantic import BaseModel
from fakts.grants.remote.demanders.types import Token


class EndpointDefaults(BaseModel):
    default_token: Dict[str, Token] = {}


class AutoSaveTokenStore(BaseModel):
    """Retrieves and stores users matching the currently
    active fakts grant"""

    settings: QtCore.QSettings
    save_key: str

    async def aput_default_token_for_endpoint(
        self, endpoint: FaktsEndpoint, token: Token
    ) -> None:
        un_storage = self.settings.value(self.save_key, None)
        if not un_storage:
            storage = EndpointDefaults()
        else:
            try:
                storage = EndpointDefaults(**json.loads(un_storage))
            except Exception:
                storage = EndpointDefaults()

        if token is None:
            if endpoint.base_url in storage.default_token:
                del storage.default_token[endpoint.base_url]
        else:
            storage.default_token[endpoint.base_url] = token

        self.settings.setValue(self.save_key, storage.json())

    async def aget_default_token_for_endpoint(
        self, endpoint: FaktsEndpoint
    ) -> Optional[FaktsEndpoint]:
        ...

        un_storage = self.settings.value(self.save_key, None)
        if not un_storage:
            return None
        try:
            storage = EndpointDefaults(**json.loads(un_storage))
            if endpoint.base_url in storage.default_token:
                return storage.default_token[endpoint.base_url]
        except Exception as e:
            print(e)
            return None

        return None

    class Config:
        arbitrary_types_allowed = True
