import logging
from qtpy import QtCore


from typing import Optional
import datetime
from fakts_next.models import ActiveFakts
from pydantic import BaseModel, ConfigDict, Field
from fakts_next.cache.model import CacheModel

logger = logging.getLogger(__name__)


class QtSettingsCache(BaseModel):
    """Retrieves and stores the active fakts in the Qt settings"""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    settings: QtCore.QSettings  # type: ignore #
    save_key: str = "fakts_cache"
    hash: str = Field(
        default_factory=lambda: "",
        description="Validating against the hash of the config",
    )
    expires_in: Optional[int] = None
    """The time in seconds for the cache to expire (None: never expires)"""

    async def aset(self, value: ActiveFakts) -> None:
        """Stores the value in the settings

        Parameters
        ----------
        value : ActiveFakts
            The value to store
        """

        cache = CacheModel(config=value.model_dump(), created=datetime.datetime.now(), hash=self.hash)

        self.settings.setValue(self.save_key, cache.model_dump_json())  # type: ignore #

    async def aload(self) -> Optional[ActiveFakts]:
        """Loads the value from the settings

        Returns
        -------
        Optional[ActiveFakts]
            The cached fakts, or None if there is no (valid) value
        """

        un_storage = self.settings.value(self.save_key, None)  # type: ignore #
        if not un_storage:
            return None

        if not isinstance(un_storage, str):
            logger.warning("Cache is not a string. Ignoring it")
            return None
        try:
            storage = CacheModel.model_validate_json(un_storage)
            if self.hash and storage.hash != self.hash:
                return None

            if self.expires_in:
                if (
                    storage.created + datetime.timedelta(seconds=self.expires_in)
                    < datetime.datetime.now()
                ):
                    return None

            return ActiveFakts.model_validate(storage.config)
        except Exception as e:
            # A corrupt cache should never break startup: treat it as a
            # cache miss and let the grant reload.
            logger.error("Could not load cache from settings. Ignoring it", exc_info=e)

        return None

    async def areset(self) -> None:
        """Resets the cache

        Removes the cached fakts from the settings.
        """

        self.settings.setValue(self.save_key, None)  # type: ignore #
