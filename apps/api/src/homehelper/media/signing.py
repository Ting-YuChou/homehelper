"""Short-lived tokens for `/v1/media/{token}`, the local stand-in for GCS signed URLs (spec §11.1).

Like a signed URL, the token alone grants read access to one attachment until it expires, so an
`<img src>` works without the session cookie. The salt keeps these tokens and session cookies
from being interchangeable even though both use the session secret.
"""

from itsdangerous import BadSignature, URLSafeTimedSerializer


class MediaSigner:
    def __init__(self, secret: str, *, ttl_s: int) -> None:
        self._serializer = URLSafeTimedSerializer(secret, salt="hh-media")
        self.ttl_s = ttl_s

    def dumps(self, attachment_id: str) -> str:
        return self._serializer.dumps(attachment_id)

    def loads(self, token: str) -> str | None:
        try:
            value = self._serializer.loads(token, max_age=self.ttl_s)
        except BadSignature:  # also covers SignatureExpired
            return None
        return value if isinstance(value, str) else None
