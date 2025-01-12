import a
import b
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

app = FastAPI()

app.include_router(a.router)
app.include_router(b.router)


@app.get("/")
def redirect_to_docs():
    return RedirectResponse("/docs")
