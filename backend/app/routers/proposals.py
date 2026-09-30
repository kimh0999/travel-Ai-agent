from typing import Optional

from fastapi import APIRouter, Body, Depends, Query

from app.core.auth import AuthUser, current_user
from app.repositories import proposals as repo
from app.schemas.common import ProposalStatus
from app.schemas.proposals import ApproveRequest, ApproveResult, MemoryProposal, ProposalGenerateResult
from app.services import approval, proposal_extractor

router = APIRouter(prefix="/api", tags=["memory-proposals"])


@router.post("/trips/{trip_id}/memory-proposals", response_model=ProposalGenerateResult, status_code=201)
def generate_proposals(trip_id: str, user: AuthUser = Depends(current_user)):
    return proposal_extractor.generate_proposals(user.uid, trip_id)


@router.get("/memory-proposals", response_model=list[MemoryProposal])
def list_proposals(status: Optional[ProposalStatus] = Query(default=None),
                   trip_id: Optional[str] = Query(default=None, max_length=64),
                   user: AuthUser = Depends(current_user)):
    return repo.list_for_owner(user.uid, status=status, trip_id=trip_id)


@router.post("/memory-proposals/{proposal_id}/approve", response_model=ApproveResult)
def approve_proposal(proposal_id: str, body: ApproveRequest = Body(default_factory=ApproveRequest),
                     user: AuthUser = Depends(current_user)):
    return approval.approve(user.uid, proposal_id, body.edited_value)


@router.post("/memory-proposals/{proposal_id}/reject", response_model=MemoryProposal)
def reject_proposal(proposal_id: str, user: AuthUser = Depends(current_user)):
    return approval.reject(user.uid, proposal_id)
