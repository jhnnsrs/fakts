from fakts.grants.remote.demanders.redeem import RedeemDemander
from fakts.grants.remote.builders import build_redeem_grant
from fakts.grants.remote import RemoteGrant
from fakts import Fakts
from pydantic import BaseModel, Field
from typing import Optional

class Requirement(BaseModel):
    service: str
    """ The service is the service that will be used to fill the key, it will be used to find the correct instance. It needs to fullfill
    the reverse domain naming scheme"""
    optional: bool = False 
    """ The optional flag indicates if the requirement is optional or not. Users should be able to use the client even if the requirement is not met. """
    description: Optional[str] = None
    """ The description is a human readable description of the requirement. Will be show to the user when asking for the requirement."""



class Manifest(BaseModel):
    """ A Manifest is a description of a client. It contains all the information
    necessary to create a set of client, release and app objects in the database.
    """
    identifier: str
    """ The identifier is a unique string that identifies the client. """
    version: str
    """ The version is a string that identifies the version of the client. """
    logo: Optional[str] = None
    """ The logo is a url to a logo that should be used for the client. """
    scopes: Optional[list[str]] = Field(default_factory=list)
    """ The scopes are a list of scopes that the client can request. """
    requirements: Optional[dict[str, Requirement]] = Field(default_factory=dict)
    """ The requirements are a list of requirements that the client needs to run on (e.g. needs GPU)"""



manifest = Manifest(
    identifier="My App",
    version="1.0",
    logo="https://www.redrat.co.uk/wp-content/uploads/2017/12/scheduler-logo.png",
    scopes=["read", "write"],
    requirements={
        "rekuest": Requirement(service="live.arkitekt.rekuest", optional=False),
    }
)


fakts = Fakts(grant=build_redeem_grant("http://localhost:8010/f/", manifest, "mysupersecretredeemtoken"))

with fakts:
    print(fakts.get())