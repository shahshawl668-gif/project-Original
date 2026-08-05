from fastapi import APIRouter, Depends
from pymongo.database import Database

from app.database import get_db
from app.deps import get_current_user
from app.envelope import ok
from app.models import LwfRate, PtSlab, SlabRule, User
from app.services.lwf_defaults import list_default_states as list_lwf_default_states
from app.services.pt_defaults import list_default_states as list_pt_default_states

router = APIRouter()


@router.get("/states")
def list_states(db: Database = Depends(get_db), user: User = Depends(get_current_user)):
    """Return distinct states known to the system.

    Sources merged:
      * seeded reference (PtSlab, LwfRate)
      * curated PT defaults catalog (selectable for one-click import)
      * tenant-managed `slab_rules` (whatever the user has already configured)
    """
    seed_pt = {s for s in PtSlab.distinct(db, "state") if s}
    seed_lwf = {s for s in LwfRate.distinct(db, "state") if s}
    default_pt = set(list_pt_default_states())
    default_lwf = set(list_lwf_default_states())
    tenant_pt = {
        s for s in SlabRule.distinct(db, "state", {"user_id": user.id, "rule_type": "PT"}) if s
    }
    tenant_lwf = {
        s for s in SlabRule.distinct(db, "state", {"user_id": user.id, "rule_type": "LWF"}) if s
    }
    pt_states = sorted(seed_pt | default_pt | tenant_pt)
    lwf_states = sorted(seed_lwf | default_lwf | tenant_lwf)
    all_states = sorted(set(pt_states) | set(lwf_states))
    return ok({"pt_states": pt_states, "lwf_states": lwf_states, "all_states": all_states})
