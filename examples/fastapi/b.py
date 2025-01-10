from fastapi import APIRouter

router = APIRouter(tags=["dog"])


@router.get("/woof")
def bark():
    return {"bark": "Woof!"}
