import c
from fastapi import APIRouter

router = APIRouter(tags=["bot"])


# print("simulating slow import", end=" ")
# sleep(2)
# print("Done!")


@router.get("/hello")
def _():
    # Or you can use `from c import value` here

    # But if you `from c import value` outside this function,
    # Changing it will trigger a reload of the server.
    return {"hello": c.value}
