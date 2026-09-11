import pydantic
from typing import Dict, Any
import datetime


class CacheModel(pydantic.BaseModel):
    """Cache file model"""

    config: Dict[str, Any]
    created: datetime.datetime
    hash: str = ""
