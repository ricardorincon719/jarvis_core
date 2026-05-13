import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Dict, Optional
from urllib.parse import urlencode

import requests


REGION_ENDPOINTS = {
    "us": "https://openapi.tuyaus.com",
    "eu": "https://openapi.tuyaeu.com",
    "cn": "https://openapi.tuyacn.com",
    "in": "https://openapi.tuyain.com",
}

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _env_first(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return ""


def cloud_configured() -> bool:
    return bool(
        _env_first("TUYA_CLOUD_ACCESS_ID", "TUYA_ACCESS_ID", "TUYA_CLIENT_ID")
        and _env_first("TUYA_CLOUD_ACCESS_KEY", "TUYA_ACCESS_KEY", "TUYA_CLIENT_SECRET")
    )


def build_cloud_client():
    if not cloud_configured():
        return None
    return TuyaCloudClient.from_env()


class TuyaCloudClient:
    def __init__(self, access_id: str, access_key: str, endpoint: str, timeout: float = 8.0):
        self.access_id = access_id
        self.access_key = access_key
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self._access_token = ""
        self._token_expires_at = 0

    @classmethod
    def from_env(cls):
        access_id = _env_first("TUYA_CLOUD_ACCESS_ID", "TUYA_ACCESS_ID", "TUYA_CLIENT_ID")
        access_key = _env_first("TUYA_CLOUD_ACCESS_KEY", "TUYA_ACCESS_KEY", "TUYA_CLIENT_SECRET")
        endpoint = _env_first("TUYA_CLOUD_ENDPOINT", "TUYA_ENDPOINT")
        if not endpoint:
            region = _env_first("TUYA_CLOUD_REGION", "TUYA_REGION").lower() or "us"
            endpoint = REGION_ENDPOINTS.get(region, REGION_ENDPOINTS["us"])
        timeout = float(os.getenv("TUYA_CLOUD_TIMEOUT", "8"))
        return cls(access_id=access_id, access_key=access_key, endpoint=endpoint, timeout=timeout)

    def get_device_details(self, device_id: str) -> Optional[Dict]:
        if not device_id:
            return None
        data = self._request("GET", f"/v1.0/devices/{device_id}", auth=True)
        result = data.get("result")
        return result if isinstance(result, dict) else None

    def list_devices(self, page_size: int = 100) -> Dict:
        params = {"page_no": 1, "page_size": max(1, min(int(page_size), 100))}
        data = self._request("GET", "/v1.0/devices", params=params, auth=True)
        result = data.get("result")
        return result if isinstance(result, dict) else {}

    def _get_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        data = self._request("GET", "/v1.0/token", params={"grant_type": "1"}, auth=False)
        result = data.get("result") or {}
        token = result.get("access_token")
        if not token:
            raise RuntimeError(data.get("msg") or "tuya_token_missing")

        expire_time = int(result.get("expire_time") or 7200)
        self._access_token = token
        self._token_expires_at = time.time() + max(60, expire_time - 60)
        return token

    def _request(self, method: str, path: str, params: Optional[Dict] = None, body: Optional[Dict] = None, auth: bool = True) -> Dict:
        method = method.upper()
        params = params or {}
        body_text = "" if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        access_token = self._get_token() if auth else ""
        headers = self._build_headers(method, path, params, body_text, access_token)
        response = requests.request(
            method,
            self.endpoint + self._url_with_params(path, params),
            headers=headers,
            data=body_text.encode("utf-8") if body_text else None,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("success") is False:
            raise RuntimeError(data.get("msg") or data.get("code") or "tuya_api_error")
        return data

    def _build_headers(self, method: str, path: str, params: Dict, body_text: str, access_token: str) -> Dict:
        t = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex
        content_hash = hashlib.sha256(body_text.encode("utf-8")).hexdigest() if body_text else EMPTY_SHA256
        string_to_sign = "\n".join([
            method,
            content_hash,
            "",
            self._url_with_params(path, params),
        ])
        sign_source = self.access_id + access_token + t + nonce + string_to_sign
        sign = hmac.new(
            self.access_key.encode("utf-8"),
            sign_source.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().upper()

        headers = {
            "client_id": self.access_id,
            "sign": sign,
            "t": t,
            "nonce": nonce,
            "sign_method": "HMAC-SHA256",
            "Content-Type": "application/json",
        }
        if access_token:
            headers["access_token"] = access_token
        return headers

    def _url_with_params(self, path: str, params: Dict) -> str:
        if not params:
            return path
        query = urlencode(sorted((str(k), str(v)) for k, v in params.items()))
        return f"{path}?{query}"
