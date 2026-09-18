"""Simple webhook receiver for AlertManager notifications."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import logging
from datetime import datetime
import json

app = FastAPI(title="AOP Alert Webhook")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.post("/")
async def webhook_root(request: Request):
    """Default webhook endpoint"""
    try:
        data = await request.json()
        logger.info(f"Received alert: {json.dumps(data, indent=2)}")
        return JSONResponse({"status": "received", "timestamp": datetime.now().isoformat()})
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.post("/critical")
async def webhook_critical(request: Request):
    """Critical alert endpoint"""
    try:
        data = await request.json()
        logger.critical(f"CRITICAL ALERT: {json.dumps(data, indent=2)}")
        # 这里可以添加发送邮件、Slack等通知逻辑
        return JSONResponse({"status": "critical_received", "timestamp": datetime.now().isoformat()})
    except Exception as e:
        logger.error(f"Error processing critical webhook: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.post("/warning")
async def webhook_warning(request: Request):
    """Warning alert endpoint"""
    try:
        data = await request.json()
        logger.warning(f"WARNING ALERT: {json.dumps(data, indent=2)}")
        return JSONResponse({"status": "warning_received", "timestamp": datetime.now().isoformat()})
    except Exception as e:
        logger.error(f"Error processing warning webhook: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)