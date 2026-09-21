from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from amrutam.api.deps import AuthUser, get_current_user, get_session
from amrutam.core.config import Settings, get_settings
from amrutam.modules.prescriptions import service
from amrutam.modules.prescriptions.pdf_store import MemoryPdfStore, MinioPdfStore, PdfStore
from amrutam.modules.prescriptions.schemas import (
    PdfUrl,
    PrescriptionCreate,
    PrescriptionOut,
    PrescriptionView,
)

router = APIRouter(tags=["prescriptions"])

_store: PdfStore | None = None


def get_store() -> PdfStore:
    global _store
    if _store is None:
        try:
            s = get_settings()
            _store = MinioPdfStore(s.s3_endpoint, s.s3_access_key, s.s3_secret_key, s.s3_bucket)
        except Exception:
            _store = MemoryPdfStore()
    return _store


@router.post(
    "/v1/consultations/{cid}/prescriptions", response_model=PrescriptionOut, status_code=201
)
async def create_rx(
    cid: str,
    payload: PrescriptionCreate,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    store: PdfStore = Depends(get_store),
) -> PrescriptionOut:
    out = await service.create_prescription(
        db, store, settings, cid, user, payload.diagnosis, payload.medicines
    )
    return PrescriptionOut(**out)


@router.get("/v1/prescriptions/{rx_id}", response_model=PrescriptionView)
async def view_rx(
    rx_id: str,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> PrescriptionView:
    return PrescriptionView(**await service.view_prescription(db, settings, rx_id, user))


@router.get("/v1/prescriptions/{rx_id}/pdf", response_model=PdfUrl)
async def rx_pdf(
    rx_id: str,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    store: PdfStore = Depends(get_store),
) -> PdfUrl:
    return PdfUrl(**await service.pdf_signed_url(db, store, rx_id, user))
