#!/usr/bin/env python3
"""
Automated unit and integration tests for NSE Swing Scanner Server and Engine.
"""

import json
from fastapi.testclient import TestClient
import scanner_engine as se
from server import app

client = TestClient(app)

def test_root_index():
    """Verify root route serves HTML and is accessible."""
    response = client.get("/")
    assert response.status_code == 200
    assert "NSE Swing Scanner" in response.text
    assert "text/html" in response.headers["content-type"]

def test_get_indices():
    """Verify available indices endpoint returns list of indices."""
    response = client.get("/api/indices")
    assert response.status_code == 200
    indices = response.json()
    assert isinstance(indices, list)
    assert len(indices) >= 10
    ids = [idx["id"] for idx in indices]
    assert "NIFTY_50" in ids
    assert "BANK_NIFTY" in ids

def test_get_config():
    """Verify configuration endpoint returns proper schema."""
    response = client.get("/api/config")
    assert response.status_code == 200
    cfg = response.json()
    assert "universe" in cfg
    assert "strategy" in cfg
    assert "indicators" in cfg
    assert "risk_management" in cfg

def test_get_scan_latest():
    """Verify latest scan endpoint returns data."""
    response = client.get("/api/scan/latest")
    assert response.status_code == 200
    data = response.json()
    assert "timestamp" in data
    assert "results" in data
    assert isinstance(data["results"], list)
    if len(data["results"]) > 0:
        first = data["results"][0]
        assert "symbol" in first
        assert "price" in first
        assert "signal" in first
        assert "stop_loss" in first
        assert "target_1" in first

def test_get_scan_status():
    """Verify status endpoint returns current state."""
    response = client.get("/api/scan/status")
    assert response.status_code == 200
    status = response.json()
    assert "is_running" in status
    assert "progress_pct" in status
    assert "status_message" in status

def test_scheduler_endpoints():
    """Verify scheduler status and toggle."""
    # Check status
    res = client.get("/api/scheduler/status")
    assert res.status_code == 200
    assert "is_active" in res.json()

    # Toggle on
    res_on = client.post("/api/scheduler/toggle", json={"enable": True, "interval_minutes": 15})
    assert res_on.status_code == 200
    assert res_on.json()["is_active"] is True
    assert res_on.json()["interval_minutes"] == 15

    # Toggle off
    res_off = client.post("/api/scheduler/toggle", json={"enable": False})
    assert res_off.status_code == 200
    assert res_off.json()["is_active"] is False

def test_stock_chart_data():
    """Verify OHLCV and indicator data endpoint for chart modal."""
    response = client.get("/api/stock/BHEL/chart")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "BHEL"
    assert "candles" in data
    assert len(data["candles"]) > 20
    first_candle = data["candles"][0]
    assert "time" in first_candle
    assert "open" in first_candle
    assert "high" in first_candle
    assert "low" in first_candle
    assert "close" in first_candle
    assert "volume" in data
    assert "ema_fast" in data
    assert "levels" in data

def test_scan_history():
    """Verify history listing and fetching."""
    res = client.get("/api/scan/history")
    assert res.status_code == 200
    history = res.json()
    assert isinstance(history, list)
    if len(history) > 0:
        stamp = history[0]["timestamp"]
        detail_res = client.get(f"/api/scan/history/{stamp}")
        assert detail_res.status_code == 200
        data = detail_res.json()
        assert "results" in data

def test_scan_trigger_endpoint():
    """Verify triggering scan with overrides accepts request."""
    # Test scan trigger
    payload = {
        "indices": ["BANK_NIFTY"],
        "min_price": 100.0,
        "max_price": 5000.0,
        "custom_symbols": ["SBIN"]
    }
    res = client.post("/api/scan", json=payload)
    # Either 200 (started) or 409 (if currently running)
    assert res.status_code in [200, 409]
