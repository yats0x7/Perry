"""Wire protocol shared by the Perry server and the desktop agent.

Everything that crosses a process boundary is defined here as a Pydantic model,
so both sides validate the same shapes.
"""

from .models import *  # noqa: F401,F403

PROTOCOL_VERSION = 1
