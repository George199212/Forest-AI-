"""Generic Telegram multi-tenant routing for Forest AI (see docs/TELEGRAM_TENANTS.md).

One poller (bot.py with FOREST_TENANT_ROUTING=1) receives every update for the shared bot
identity and queues tenant updates in that tenant's own SQLite DB. One worker per tenant
(telegram_tenants/worker.py) consumes the queue with that instance's handlers.
"""
import sys


def install_module_aliases():
    """Expose the package modules under their historical top-level names.

    Instance handler copies (telegram_handlers.py) do `from tenant_runtime import make_bot`.
    The alias makes that import return this package's module, so the worker and the handlers
    share one CURRENT context variable instead of two independent copies.
    """
    from . import company_context, tenant_runtime
    sys.modules.setdefault('company_context', company_context)
    sys.modules.setdefault('tenant_runtime', tenant_runtime)
