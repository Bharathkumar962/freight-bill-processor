from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pathlib import Path
from app.db.session import init_db
from app.db.graph import load_graph
from app.api.routes import router

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    load_graph("seed_data_logistics.json")
    print("✅ DB tables created and graph loaded.")
    yield


app = FastAPI(
    title="Freight Bill Processor",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def dashboard():
    return FileResponse(str(STATIC_DIR / "freight_bill_dashboard.html"))


@app.get("/health")
def health():
    return {"status": "ok"}