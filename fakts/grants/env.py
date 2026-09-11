import logging
import os

from pydantic import BaseModel, ValidationError

from fakts.grants.errors import GrantError
from fakts.models import ActiveFakts

logger = logging.getLogger(__name__)


def _describe(error: ValidationError) -> str:
    """Summarise a validation failure without echoing the document.

    The document being validated is the app's credential. Both pydantic's
    ``str(e)`` and the raw source render the offending values, so a single
    malformed ``$FAKTS`` would otherwise put a live refresh token into
    stdout — and from there into whatever collects the logs. Report only
    where the problem is and what kind it was.
    """
    return "; ".join(
        f"{'.'.join(str(part) for part in problem['loc']) or '<root>'}: {problem['type']}"
        for problem in error.errors()
    )


class EnvGrant(BaseModel):
    """Loads the active fakts from the environment.

    This grant is meant for containers and other pre-provisioned
    environments where the configuration is injected from the outside
    instead of being negotiated with a Fakts server.

    Two environment variables are checked, in order:

    1. ``json_var`` (default ``FAKTS``): the full configuration as an
       inline JSON string.
    2. ``file_var`` (default ``FAKTS_FILE``): a path to a JSON file
       containing the configuration (e.g. a mounted secret).

    The injected ``auth`` block must be a protocol-v2 credential — a
    ``client_id`` and a ``refresh_token``, not a client secret. Servers no
    longer issue client credentials to fakts apps.

    Note that refresh tokens rotate: the injected one is spent the first
    time it is used, and the replacement lives only in the cache. Give such
    a deployment a writable cache path, or provision it with a redeem token
    instead so it can re-authorize itself unattended.

    Example:
        ```bash
        export FAKTS='{"self": {...}, "auth": {"client_id": "...", "refresh_token": "...", "token_endpoint": "https://.../o/token/"}, "instances": {...}}'
        # or
        export FAKTS_FILE=/run/secrets/fakts.json
        ```

        ```python
        async with Fakts(grant=EnvGrant(), manifest=manifest) as fakts:
            alias = await fakts.aget_alias("rekuest")
        ```
    """

    json_var: str = "FAKTS"
    """The environment variable holding the configuration as inline JSON"""

    file_var: str = "FAKTS_FILE"
    """The environment variable holding a path to a JSON configuration file"""

    requires_user_interaction: bool = False
    """Re-reading the environment costs nothing and needs nobody, so the
    client may do it unattended when a session can no longer be renewed.
    Without this a container would raise "needs someone at a browser" for a
    credential it could simply have re-read."""

    async def aload(self) -> ActiveFakts:
        """Loads the active fakts from the environment.

        Returns
        -------
        ActiveFakts
            The configuration loaded from the environment.

        Raises
        ------
        GrantError
            If neither environment variable is set, the file does not
            exist, or the content is not a valid fakts configuration.
        """
        raw = os.environ.get(self.json_var)
        if raw:
            try:
                return ActiveFakts.model_validate_json(raw)
            except ValidationError as e:
                raise GrantError(
                    f"${self.json_var} is set, but its content is not a valid "
                    f"fakts configuration. Problems: {_describe(e)}"
                ) from e

        path = os.environ.get(self.file_var)
        if path:
            if not os.path.exists(path):
                raise GrantError(
                    f"${self.file_var} points to '{path}', but that file does not exist."
                )
            try:
                with open(path, "r") as f:
                    content = f.read()
            except OSError as e:
                raise GrantError(
                    f"Could not read the fakts configuration file '{path}' "
                    f"(from ${self.file_var}): {e}"
                ) from e
            try:
                return ActiveFakts.model_validate_json(content)
            except ValidationError as e:
                raise GrantError(
                    f"The file '{path}' (from ${self.file_var}) does not contain "
                    f"a valid fakts configuration. Problems: {_describe(e)}"
                ) from e

        raise GrantError(
            f"No fakts configuration found in the environment: neither "
            f"${self.json_var} (inline JSON) nor ${self.file_var} "
            f"(path to a JSON file) is set."
        )
