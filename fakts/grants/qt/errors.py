class QtGrantError(Exception):
    pass


class NoRunningQtApplication(QtGrantError):
    pass
