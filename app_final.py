"""DNS-сервис: хранит A-записи (домен -> IPv4-адрес)."""


from fastapi import FastAPI


app = FastAPI(title="DNS-сервис")


@app.get("/")
def root():
    return {"message": "DNS-сервис работает", "docs": "/docs"}
