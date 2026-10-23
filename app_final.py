"""DNS-сервис: хранит A-записи (домен -> IPv4-адрес)."""

import ipaddress
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Path, Request
from pydantic import BaseModel, field_validator

load_dotenv()

APP_NAME = os.getenv("APP_NAME", "DNS-сервис")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
ADMIN_KEY = os.getenv("ADMIN_KEY", "")

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("dns_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Запуск %s %s", APP_NAME, APP_VERSION)
    if not ADMIN_KEY:
        logger.warning("ADMIN_KEY не задан: создание, изменение и удаление записей недоступны")
    yield
    logger.info("Остановка сервиса")


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "%s %s -> %d (%.1f мс)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")


def normalize_domain(name: str) -> str:
    """Проверяет доменное имя и приводит его к нижнему регистру без точки в конце."""
    domain = name.strip().lower()
    domain = domain.removesuffix(".")
    labels = domain.split(".")
    if (
        len(domain) > 253
        or len(labels) < 2
        or not all(LABEL.fullmatch(label) for label in labels)
        or labels[-1].isdigit()
    ):
        raise ValueError(f"Недопустимое доменное имя: {name!r}")
    return domain


class RecordIn(BaseModel):
    name: str
    ip: str

    @field_validator("name")
    @classmethod
    def check_name(cls, value: str) -> str:
        return normalize_domain(value)

    @field_validator("ip")
    @classmethod
    def check_ip(cls, value: str) -> str:
        try:
            return str(ipaddress.IPv4Address(value.strip()))
        except ValueError:
            raise ValueError(f"Недопустимый IPv4-адрес: {value!r}") from None


class RecordIp(BaseModel):
    ip: str

    @field_validator("ip")
    @classmethod
    def check_ip(cls, value: str) -> str:
        try:
            return str(ipaddress.IPv4Address(value.strip()))
        except ValueError:
            raise ValueError(f"Недопустимый IPv4-адрес: {value!r}") from None


class Record(BaseModel):
    name: str
    type: str = "A"
    ip: str


records: dict[str, Record] = {}


def domain_or_422(name: str) -> str:
    try:
        return normalize_domain(name)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


def get_or_404(name: str) -> Record:
    record = records.get(domain_or_422(name))
    if record is None:
        raise HTTPException(status_code=404, detail=f"Запись {name} не найдена")
    return record


def require_admin(admin_key: str | None) -> None:
    if not admin_key:
        logger.warning("Отказ: нет заголовка X-Admin-Key")
        raise HTTPException(status_code=401, detail="Нужен заголовок X-Admin-Key")
    if not ADMIN_KEY or not secrets.compare_digest(
        admin_key.encode(), ADMIN_KEY.encode()
    ):
        logger.warning("Отказ: неверный ключ администратора")
        raise HTTPException(status_code=403, detail="Неверный ключ администратора")


@app.get("/")
def root():
    return {"message": "DNS-сервис работает", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/version")
def version():
    return {"version": APP_VERSION}


@app.get("/records")
def list_records():
    return sorted(records.values(), key=lambda record: record.name)


@app.get("/records/{name}")
def get_record(name: str = Path(examples=["example.com"])):
    return get_or_404(name)


@app.post("/records", status_code=201)
def create_record(
    data: RecordIn,
    x_admin_key: str | None = Header(default=None),
):
    require_admin(x_admin_key)
    if data.name in records:
        logger.warning("Конфликт: запись %s уже существует", data.name)
        raise HTTPException(
            status_code=409, detail=f"Запись {data.name} уже существует"
        )
    record = Record(name=data.name, ip=data.ip)
    records[record.name] = record
    logger.info("Создана запись %s A %s", record.name, record.ip)
    return record


@app.patch("/records/{name}")
def update_record(
    name: str,
    data: RecordIp,
    x_admin_key: str | None = Header(default=None),
):
    require_admin(x_admin_key)
    record = get_or_404(name)
    updated = record.model_copy(update={"ip": data.ip})
    records[updated.name] = updated
    logger.info("Обновлена запись %s A %s", updated.name, updated.ip)
    return updated


@app.delete("/records/{name}", status_code=204)
def delete_record(
    name: str,
    x_admin_key: str | None = Header(default=None),
):
    require_admin(x_admin_key)
    record = get_or_404(name)
    del records[record.name]
    logger.info("Удалена запись %s A %s", record.name, record.ip)
