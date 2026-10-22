"""DNS-сервис: хранит A-записи (домен -> IPv4-адрес)."""

import os

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

APP_NAME = os.getenv("APP_NAME", "DNS-сервис")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")


app = FastAPI(title=APP_NAME, version=APP_VERSION)


@app.get("/")
def root():
    return {"message": "DNS-сервис работает", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/version")
def version():
    return {"version": APP_VERSION}
