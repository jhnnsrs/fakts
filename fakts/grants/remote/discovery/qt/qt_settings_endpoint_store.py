import logging
from qtpy import QtCore

from fakts.grants.remote.types import FaktsEndpoint
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class QtSettingsEndpointStore(BaseModel):
    """Retrieves and stores users matching the currently
    active fakts grant"""

    settings: QtCore.QSettings
    save_key: str

    async def aput_default_endpoint(self, endpoint: Optional[FaktsEndpoint]) -> None:
        """A function that stores the default endpoint

        Parameters
        ----------
        endpoint : FaktsEndpoint
            The endpoint to put
        """
        self.settings.setValue(self.save_key, endpoint.json() if endpoint else None)

    async def aget_default_endpoint(self) -> Optional[FaktsEndpoint]:
        """A function that gets the default endpoint

        Returns
        -------
        Optional[FaktsEndpoint]
            The stored endpoint, or None if there is no endpoint

        """

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
        """Pydantic Config"""

        arbitrary_types_allowed = True
