"""
iscs_assets.py — M2.3 compatibility shim.

The asset store was relocated to ``adapters/driven/persistence/asset_store.py``
(the Hexagonal driven-persistence layer). This file re-exports its full surface —
including module-level privates such as ``_BINDING_RESOLVERS`` and ``_APP_DIR`` —
so every existing ``from iscs_assets import …`` import, and tests that mutate
``iscs_assets._BINDING_RESOLVERS``, keep working unchanged. Retired in M6.

(Asset entity value objects already live in ``core/domain/assets.py``, which
``asset_store`` imports and this shim therefore also re-exports.)
"""
import adapters.driven.persistence.asset_store as _store
from adapters.driven.persistence.asset_store import *  # noqa: F401,F403

# Re-export ALL module-level names (incl. privates) so `iscs_assets.X` resolves to
# the exact same objects (same _BINDING_RESOLVERS dict, same _APP_DIR global, …).
globals().update({k: v for k, v in vars(_store).items() if not k.startswith("__")})
