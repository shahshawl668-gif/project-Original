from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import LwfRate, PtSlab, SlabRule, User
from app.services.lwf_defaults import list_default_states as list_lwf_default_states
from app.services.pt_defaults import list_default_states as list_pt_default_states

router = APIRouter()


@router.get("/states")
def list_states(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Return distinct states known to the system.

    Sources merged:
      * seeded reference (PtSlab, LwfRate)
      * curated PT defaults catalog (selectable for one-click import)
      * tenant-managed `slab_rules` (whatever the user has already configured)
    """
    seed_pt = {row[0] for row in db.execute(select(PtSlab.state).distinct()).all() if row[0]}
    seed_lwf = {row[0] for row in db.execute(select(LwfRate.state).distinct()).all() if row[0]}
    default_pt = set(list_pt_default_states())
    default_lwf = set(list_lwf_default_states())
    tenant_pt = {
        row[0]
        for row in db.execute(
            select(SlabRule.state)
            .where(SlabRule.user_id == user.id, SlabRule.rule_type == "PT")
            .distinct()
        ).all()
        if row[0]
    }
    tenant_lwf = {
        row[0]
        for row in db.execute(
            select(SlabRule.state)
            .where(SlabRule.user_id == user.id, SlabRule.rule_type == "LWF")
            .distinct()
        ).all()
        if row[0]
    }
    pt_states = sorted(seed_pt | default_pt | tenant_pt)
    lwf_states = sorted(seed_lwf | default_lwf | tenant_lwf)
    all_states = sorted(set(pt_states) | set(lwf_states))
    return {"pt_states": pt_states, "lwf_states": lwf_states, "all_states": all_states}
