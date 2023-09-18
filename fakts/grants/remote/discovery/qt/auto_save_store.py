from fakts import Fakts
import logging
from qtpy import QtCore

from fakts.grants.remote.types import FaktsEndpoint

logger = logging.getLogger(__name__)
from typing import List, Dict, Optional

import json
from pydantic import BaseModel, Field


class AutoSaveEndpointStore(BaseModel):
    """Retrieves and stores users matching the currently
    active fakts grant"""

    settings: QtCore.QSettings
    save_key: str

    async def aput_default_endpoint(self, endpoint: Optional[FaktsEndpoint]) -> None:
        self.settings.setValue(self.save_key, endpoint.json() if endpoint else None)

    async def aget_default_endpoint(self) -> Optional[FaktsEndpoint]:
        ...

        un_storage = self.settings.value(self.save_key, None)
        if not un_storage:
            return None
        try:
            storage = FaktsEndpoint.parse_raw(un_storage)
            return storage
        except Exception as e:
            print(e)

        return None

    class Config:
        arbitrary_types_allowed = True
