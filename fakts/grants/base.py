from koil import koil


class GrantException(Exception):
    pass


class FaktsGrant:


    async def aload(self, **kwargs):
        raise NotImplementedError()

    def load(self, as_task=False, **kwargs):
        return koil(self.load(**kwargs), as_task=as_task)
