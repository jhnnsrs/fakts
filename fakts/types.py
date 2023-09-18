from pydantic import BaseModel
from typing import Dict, Any


class FaktsRequest(BaseModel):
    is_refresh: bool = False
    context: Dict[str, Any]
