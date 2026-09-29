"""What a service is handed instead of the whole configuration client.

A service needs two things from fakts, and only two: the **address** of each
service it requires, and a way to get an **access token**. The first is an
:class:`~fakts.models.Alias`, resolved once when the run connects; the second is
a :class:`TokenLoader`.

Neither is the fakts client. That is the point: a builder written against these
is a pure function of resolved configuration, so it can be built from a literal
address and a two-line token stub, with no configuration system in sight.

An alias is resolved once per run and does not change under a live client. An
alias is a route to *one specific service*, and changing which service a client
talks to mid-execution is not supported -- if a deployment moves, the run ends
and a new one resolves afresh. A token, by contrast, must stay live: it expires,
and rotating it is what :class:`TokenLoader` is for.
"""

from arkitekt_spec.declare.wiring import TokenLoader

__all__ = ["TokenLoader"]
