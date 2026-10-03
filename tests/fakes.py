"""Test doubles for HTTP sessions."""

import requests


class FakeResponse:
    def __init__(self, payload=None, status=200, content=b""):
        self.payload = payload
        self.status_code = status
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        if self.payload is None:
            raise ValueError("no json")
        return self.payload


class FakeSession:
    """Maps URL substrings to responses (or exceptions); records requests."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def get(self, url, params=None, timeout=None):
        self.requests.append((url, params))
        for fragment, response in self.routes.items():
            if fragment in url:
                if isinstance(response, Exception):
                    raise response
                return response(params) if callable(response) else response
        return FakeResponse(status=404)
