from fakts.grants.errors import GrantException


class RemoteGrantException(GrantException):
    pass


class ClaimGrantException(RemoteGrantException):
    pass
