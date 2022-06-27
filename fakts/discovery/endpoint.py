from pydantic import BaseModel


class FaktsEndpoint(BaseModel):
    base_url = "http://localhost:8000/f"
    name: str = "Helper"
