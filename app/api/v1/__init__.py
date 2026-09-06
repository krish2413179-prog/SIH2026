"""API v1 router — aggregates all sub-routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.attributions import router as attributions_router
from app.api.v1.auth import router as auth_router
from app.api.v1.ml_report import router as ml_report_router
from app.api.v1.cases import router as cases_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.intel import router as intel_router
from app.api.v1.reports import router as reports_router
from app.api.v1.risk import router as risk_router
from app.api.v1.sahyog import router as sahyog_router
from app.api.v1.traces import router as traces_router
from app.api.v1.wallets import router as wallets_router
from app.api.v1.websocket import router as websocket_router

router = APIRouter(prefix="/api/v1")

router.include_router(auth_router)
router.include_router(cases_router)
router.include_router(dashboard_router)
router.include_router(wallets_router)
router.include_router(traces_router)
router.include_router(attributions_router)
router.include_router(ml_report_router)
router.include_router(risk_router)
router.include_router(intel_router)
router.include_router(reports_router)
router.include_router(sahyog_router)
router.include_router(websocket_router)

