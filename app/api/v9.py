from __future__ import annotations

import json
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import current_actor
from app.core.continuous_intelligence_models import (
    ContinuousIntelligenceSummary, InAppNotification, IntelligenceAlert, IntelligenceAlertEvent,
    MonitoringPollEvent, MonitoringPollJob, MonitoringSource, MonitoringSourceCreate,
    MonitoringSourceStatusRequest, NotificationSubscription, NotificationSubscriptionCreate,
    WatchlistCreate, WatchlistManifest,
)
from app.services.continuous_intelligence import ContinuousIntelligenceService


router = APIRouter()
service = ContinuousIntelligenceService()


def _actor(request: Request):
    return current_actor(request)


@router.get("/organizations/{organization_id}/projects/{project_id}/monitoring/sources", response_model=list[MonitoringSource])
def source_list(organization_id: str, project_id: str, request: Request):
    return service.list_sources(organization_id, project_id, _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/monitoring/sources", response_model=MonitoringSource)
def source_create(organization_id: str, project_id: str, payload: MonitoringSourceCreate, request: Request):
    return service.create_source(organization_id, project_id, payload, _actor(request))


@router.get("/organizations/{organization_id}/projects/{project_id}/monitoring/sources/{source_id}", response_model=MonitoringSource)
def source_detail(organization_id: str, project_id: str, source_id: str, request: Request):
    return service.get_source(organization_id, project_id, source_id, _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/monitoring/sources/{source_id}/poll", response_model=MonitoringPollJob)
def source_poll(organization_id: str, project_id: str, source_id: str, request: Request):
    return service.queue_poll(organization_id, project_id, source_id, _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/monitoring/sources/{source_id}/status", response_model=MonitoringSource)
def source_status(organization_id: str, project_id: str, source_id: str, payload: MonitoringSourceStatusRequest, request: Request):
    return service.update_source_status(organization_id, project_id, source_id, payload, _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/monitoring/sources/{source_id}/clone", response_model=MonitoringSource)
def source_clone(organization_id: str, project_id: str, source_id: str, request: Request):
    return service.clone_source(organization_id, project_id, source_id, _actor(request))


@router.get("/organizations/{organization_id}/projects/{project_id}/monitoring/polls", response_model=list[MonitoringPollJob])
def poll_list(organization_id: str, project_id: str, request: Request, limit: int = Query(default=100, ge=1, le=500)):
    return service.list_polls(organization_id, project_id, _actor(request), limit)


@router.get("/organizations/{organization_id}/projects/{project_id}/monitoring/polls/{poll_id}", response_model=MonitoringPollJob)
def poll_detail(organization_id: str, project_id: str, poll_id: str, request: Request):
    return service.get_poll(organization_id, project_id, poll_id, _actor(request))


@router.get("/organizations/{organization_id}/projects/{project_id}/monitoring/polls/{poll_id}/events", response_model=list[MonitoringPollEvent])
def poll_events(organization_id: str, project_id: str, poll_id: str, request: Request, after_seq: int = Query(default=0, ge=0)):
    return service.list_poll_events(organization_id, project_id, poll_id, _actor(request), after_seq=after_seq)


@router.get("/organizations/{organization_id}/projects/{project_id}/watchlists", response_model=list[WatchlistManifest])
def watchlist_list(organization_id: str, project_id: str, request: Request):
    return service.list_watchlists(organization_id, project_id, _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/watchlists", response_model=WatchlistManifest)
def watchlist_create(organization_id: str, project_id: str, payload: WatchlistCreate, request: Request):
    return service.create_watchlist(organization_id, project_id, payload, _actor(request))


@router.get("/organizations/{organization_id}/projects/{project_id}/watchlists/{watchlist_id}", response_model=WatchlistManifest)
def watchlist_detail(organization_id: str, project_id: str, watchlist_id: str, request: Request):
    return service.get_watchlist(organization_id, project_id, watchlist_id, _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/watchlists/{watchlist_id}/activate", response_model=WatchlistManifest)
def watchlist_activate(organization_id: str, project_id: str, watchlist_id: str, request: Request):
    return service.set_watchlist_status(organization_id, project_id, watchlist_id, "active", _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/watchlists/{watchlist_id}/pause", response_model=WatchlistManifest)
def watchlist_pause(organization_id: str, project_id: str, watchlist_id: str, request: Request):
    return service.set_watchlist_status(organization_id, project_id, watchlist_id, "paused", _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/watchlists/{watchlist_id}/clone", response_model=WatchlistManifest)
def watchlist_clone(organization_id: str, project_id: str, watchlist_id: str, request: Request):
    return service.clone_watchlist(organization_id, project_id, watchlist_id, _actor(request))


@router.get("/organizations/{organization_id}/projects/{project_id}/alerts", response_model=list[IntelligenceAlert])
def alert_list(organization_id: str, project_id: str, request: Request, status: str | None = None, limit: int = Query(default=200, ge=1, le=500)):
    return service.list_alerts(organization_id, project_id, _actor(request), status=status, limit=limit)


@router.get("/organizations/{organization_id}/projects/{project_id}/alerts/{alert_id}", response_model=IntelligenceAlert)
def alert_detail(organization_id: str, project_id: str, alert_id: str, request: Request):
    return service.get_alert(organization_id, project_id, alert_id, _actor(request))


@router.get("/organizations/{organization_id}/projects/{project_id}/alerts/{alert_id}/events", response_model=list[IntelligenceAlertEvent])
def alert_events(organization_id: str, project_id: str, alert_id: str, request: Request):
    return service.list_alert_events(organization_id, project_id, alert_id, _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/alerts/{alert_id}/acknowledge", response_model=IntelligenceAlert)
def alert_acknowledge(organization_id: str, project_id: str, alert_id: str, request: Request):
    return service.set_alert_status(organization_id, project_id, alert_id, "acknowledged", _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/alerts/{alert_id}/dismiss", response_model=IntelligenceAlert)
def alert_dismiss(organization_id: str, project_id: str, alert_id: str, request: Request):
    return service.set_alert_status(organization_id, project_id, alert_id, "dismissed", _actor(request))


@router.get("/organizations/{organization_id}/summary", response_model=dict)
def organization_summary(organization_id: str, request: Request):
    return {"organization_id": organization_id, "notifications": len(service.list_notifications(organization_id, _actor(request), unread_only=True))}


@router.get("/organizations/{organization_id}/projects/{project_id}/intelligence/summary", response_model=ContinuousIntelligenceSummary)
def intelligence_summary(organization_id: str, project_id: str, request: Request):
    return service.summary(organization_id, project_id, _actor(request))


@router.get("/notifications", response_model=list[InAppNotification])
def notification_list(request: Request, after_seq: int = Query(default=0, ge=0), unread_only: bool = False, limit: int = Query(default=200, ge=1, le=500)):
    organization_id = request.state.organization_id
    return service.list_notifications(organization_id, _actor(request), after_seq=after_seq, unread_only=unread_only, limit=limit)


@router.get("/notifications/stream")
def notification_stream(request: Request, after_seq: int = Query(default=0, ge=0)):
    organization_id = request.state.organization_id
    last = request.headers.get("last-event-id")
    if last and last.isdigit():
        after_seq = max(after_seq, int(last))
    actor = _actor(request)

    def events():
        cursor = after_seq
        idle = 0
        while idle < 20:
            rows = service.list_notifications(organization_id, actor, after_seq=cursor, limit=200)
            for item in rows:
                cursor = max(cursor, item.seq)
                yield f"id: {item.seq}\nevent: notification\ndata: {json.dumps(item.model_dump(mode='json'), ensure_ascii=False)}\n\n"
            if not rows:
                idle += 1
                yield ": keepalive\n\n"
                time.sleep(0.5)
            else:
                idle = 0
    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/notifications/{notification_id}/read", response_model=InAppNotification)
def notification_read(notification_id: str, request: Request):
    return service.mark_notification_read(request.state.organization_id, notification_id, _actor(request))


@router.post("/notifications/read-all", response_model=dict)
def notification_read_all(request: Request):
    return service.mark_all_notifications_read(request.state.organization_id, _actor(request))


@router.get("/notification-subscriptions", response_model=list[NotificationSubscription])
def subscription_list(request: Request):
    return service.list_subscriptions(request.state.organization_id, _actor(request))


@router.post("/notification-subscriptions", response_model=NotificationSubscription)
def subscription_create(payload: NotificationSubscriptionCreate, request: Request):
    return service.create_subscription(request.state.organization_id, payload, _actor(request))


@router.post("/notification-subscriptions/{subscription_id}/pause", response_model=NotificationSubscription)
def subscription_pause(subscription_id: str, request: Request):
    return service.pause_subscription(request.state.organization_id, subscription_id, _actor(request))


@router.post("/notification-subscriptions/{subscription_id}/test", response_model=dict)
def subscription_test(subscription_id: str, request: Request):
    return service.test_subscription(request.state.organization_id, subscription_id, _actor(request))
