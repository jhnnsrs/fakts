class FaktsError(Exception):
    pass


class NoFaktsFound(FaktsError):
    pass


class NoGrantConfigured(FaktsError):
    pass


class GroupsNotFound(FaktsError):
    pass


class NoGrantSucessfull(FaktsError):
    pass
