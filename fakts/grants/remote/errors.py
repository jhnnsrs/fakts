from fakts.grants.errors import GrantError


class RemoteGrantError(GrantError):
    pass


class ClaimError(RemoteGrantError):
    pass
