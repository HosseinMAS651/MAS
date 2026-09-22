"""نقطهٔ ورود برنامه.

اجرای محلی:
    uvicorn main:app --reload
اجرای تولید (همان چیزی که render.yaml استفاده می‌کند):
    uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers
"""

from mas_app.main import app

__all__ = ["app"]
