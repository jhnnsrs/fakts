from pydantic import SecretStr
from fakts.grants.remote.types import FaktsEndpoint, FaktsRequest
from pydantic import BaseModel


class StaticDemander(BaseModel):
    """Static Grant

    A static demander is a remote grant that has a static token. This token can
    for example have been retrieved from a configuration file beforehand and uniquely
    identifies the application on the fakts server. When using the static grant make
    sure that the token is not shared with other applications. As they can then mimik
    your application.

    Attention: If you are using the static grant, make sure that the token is not
    shared with other applications. As they can then mimik your application, especially
    when this static token maps to an client-credentials (user) application on the fakts
    server, as this application will then be able to access the data of the user that
    granted the application in the first place.

    """

    token: SecretStr
    """ The token (secret) that uniquely identifies this application on the fakts server."""

    async def ademand(self, endpoint: FaktsEndpoint, request: FaktsRequest) -> str:
        """Demand a token from the endpoint

        Retrieve the token that was provided to the demander

        Parameters
        ----------
        endpoint : FaktsEndpoint
            The endpoint to demand the token from

        request : FaktsRequest
            The request to use for the demand

        Returns
        -------
        str
            The token that was retrieved
        """
        return self.token.get_secret_value()
