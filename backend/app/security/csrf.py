import secrets

from fastapi import Cookie, Header, HTTPException, status

# Not httponly — this is the whole point of double-submit: frontend JS must
# be able to read the cookie value itself, to echo it back as a header.
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


async def verify_csrf(
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE),
    csrf_header: str | None = Header(default=None, alias=CSRF_HEADER),
) -> None:
    """Double-submit CSRF check for state-changing routes.

    An attacker's cross-site page can rely on the browser auto-attaching
    our cookies to a forged request (that's the CSRF vector SameSite=strict
    already blocks in most cases) — but same-origin policy stops that page
    from ever reading the cookie's *value* to also set a matching header.
    So a request lacking a correct header, even one carrying valid session
    cookies, didn't originate from our own frontend JS.
    """
    if not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing or invalid")
