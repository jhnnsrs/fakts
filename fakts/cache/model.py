import datetime
from typing import Any

import pydantic


class CacheModel(pydantic.BaseModel):
    """Cache file model"""

    config: dict[str, Any]
    created: datetime.datetime
    hash: str = ""
