from app.core.config import get_settings


async def test_auth_cookies_support_secure_cross_site_sessions(client, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.setenv("COOKIE_SAMESITE", "none")
    get_settings.cache_clear()

    try:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "cookie-policy@example.com",
                "display_name": "Cookie Policy",
                "password": "correct-horse-battery-staple",
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 201
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 3
    assert all("SameSite=none" in cookie for cookie in cookies)
    assert all("Secure" in cookie for cookie in cookies)
    assert any(cookie.startswith("arcscrow_session=") and "HttpOnly" in cookie for cookie in cookies)
    assert any(cookie.startswith("arcscrow_refresh=") and "HttpOnly" in cookie for cookie in cookies)
    assert any(cookie.startswith("arcscrow_csrf=") and "HttpOnly" not in cookie for cookie in cookies)
