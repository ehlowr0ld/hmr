from fastapi import APIRouter

router = APIRouter(tags=["bot"])


# print("simulating slow import", end=" ")
# sleep(2)
# print("Done!")


@router.get("/hello")
def _():
    return {"hello": "world"}
