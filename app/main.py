import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
load_dotenv()

import uvicorn

from app.api.health import router as health_router
from app.api.chat import router as chat_router
from app.logger import setup_logging, get_logger


app = FastAPI(title="mocking-flowise API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize logging once app is created
setup_logging()
log = get_logger(__name__)


app.include_router(health_router)
app.include_router(chat_router)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "6666"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
    log.info("FastAPI application initialized")
