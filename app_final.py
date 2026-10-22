"""DNS-сервис: хранит A-записи (домен -> IPv4-адрес)."""

import ipaddress
import os
import re

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel, field_validator

load_dotenv()

APP_NAME = os.getenv("APP_NAME", "DNS-сервис")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")


app = FastAPI(title=APP_NAME, version=APP_VERSION)


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
):
    if data.name in records:
        raise HTTPException(
            status_code=409, detail=f"Запись {data.name} уже существует"
        )
    record = Record(name=data.name, ip=data.ip)
    records[record.name] = record
    return record


@app.patch("/records/{name}")
def update_record(
    name: str,
    data: RecordIp,
):
    record = get_or_404(name)
    updated = record.model_copy(update={"ip": data.ip})
    records[updated.name] = updated
    return updated


@app.delete("/records/{name}", status_code=204)
def delete_record(
    name: str,
):
    record = get_or_404(name)
    del records[record.name]
