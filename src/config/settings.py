import os

ENV = os.getenv("ENVIRONMENT", "dev").lower()

if ENV == "prod":
    from .prod import *
else:
    from .dev import *
