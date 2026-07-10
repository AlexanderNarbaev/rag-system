# proxy/app/api/widget.py
"""Chat widget endpoints — HTML page and standalone JavaScript."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

router = APIRouter(tags=["widget"])


@router.get("/v1/widget")
async def serve_widget():
    """Serve the embeddable RAG chat widget HTML page.

    The widget connects to /v1/chat/completions via SSE streaming.
    Access control: WIDGET_ENABLED config flag; RBAC: Role.USER when AUTH_ENABLED.
    """
    widget_path = Path(__file__).parent.parent / "static" / "widget.html"
    if not widget_path.exists():
        raise HTTPException(status_code=404, detail="Widget not found")
    return HTMLResponse(content=widget_path.read_text(encoding="utf-8"))


@router.get("/v1/widget.js")
async def serve_widget_js():
    """Serve the standalone RAG chat widget JavaScript.

    Can be embedded in any page:
      <script src="/v1/widget.js"></script>
      <div id="rag-chat"></div>
      <script>RAGChatWidget.init({container:'rag-chat'});</script>
    """
    widget_path = Path(__file__).parent.parent / "static" / "widget.js"
    if not widget_path.exists():
        raise HTTPException(status_code=404, detail="Widget JS not found")
    return Response(
        content=widget_path.read_text(encoding="utf-8"),
        media_type="application/javascript",
    )
