from __future__ import annotations

import pytest
from c19_asset_service.api import create_api_app
from c19_asset_service.config import AssetApiSettings
from c19_asset_asgi_client import ASGIClient
from c19_asset_test_helpers import GATEWAY_TOKEN, SERVICE_TOKEN


@pytest.fixture
def api_settings(tmp_path):
    return AssetApiSettings(
        database_url=f"sqlite:///{tmp_path / 'asset.db'}",
        service_token=SERVICE_TOKEN,
        gateway_token=GATEWAY_TOKEN,
        dataset_id="dataset-test-001",
        upload_ticket_ttl_seconds=900,
        download_ticket_ttl_seconds=60,
        download_ticket_max_uses=3,
        max_pending_uploads_per_owner=3,
    )


@pytest.fixture
def app(api_settings):
    return create_api_app(api_settings, create_schema=True)


@pytest.fixture
def client(app):
    try:
        yield ASGIClient(app)
    finally:
        app.state.database_executor.shutdown(wait=True, cancel_futures=True)
        app.state.database.dispose()


@pytest.fixture
def service_headers():
    return {"Authorization": f"Bearer {SERVICE_TOKEN}"}


@pytest.fixture
def gateway_headers():
    return {"Authorization": f"Bearer {GATEWAY_TOKEN}"}
