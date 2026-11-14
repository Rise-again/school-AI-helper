"""教务查询接口。

契约由前端先行实现（P6-05），这里保持字段不变：
- GET    /edu/status   → {bound, student_no, updated_at}
- POST   /edu/bind     → 同上
- DELETE /edu/bind     → null
- GET    /edu/schedule → {items: [{weekday, sections, course, teacher, location, weeks}]}
- GET    /edu/grades   → {terms: [...], items: [{course, credit, score, gpa, term}]}
- GET    /edu/credits  → {required, earned, gpa, categories: [{name, required, earned}]}

权限：仅学生角色、仅本人数据（见 01-需求基线 权限矩阵）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, envelope, get_edu_service, require_roles
from app.services.edu_service import EduService

router = APIRouter(prefix="/edu", tags=["edu"])


class BindIn(BaseModel):
    student_no: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


@router.get("/status", summary="教务绑定状态")
async def edu_status(
    user: CurrentUser = Depends(require_roles("student")),
    svc: EduService = Depends(get_edu_service),
) -> dict:
    return envelope(0, "ok", await svc.status(user.id))


@router.post("/bind", summary="绑定教务账号")
async def edu_bind(
    payload: BindIn,
    user: CurrentUser = Depends(require_roles("student")),
    svc: EduService = Depends(get_edu_service),
) -> dict:
    data = await svc.bind(user_id=user.id, student_no=payload.student_no, password=payload.password)
    return envelope(0, "绑定成功", data)


@router.delete("/bind", summary="解绑教务账号")
async def edu_unbind(
    user: CurrentUser = Depends(require_roles("student")),
    svc: EduService = Depends(get_edu_service),
) -> dict:
    await svc.unbind(user.id)
    return envelope(0, "已解绑", None)


@router.get("/schedule", summary="本学期课表")
async def edu_schedule(
    user: CurrentUser = Depends(require_roles("student")),
    svc: EduService = Depends(get_edu_service),
) -> dict:
    return envelope(0, "ok", {"items": await svc.schedule(user.id)})


@router.get("/grades", summary="成绩列表（可选学期）")
async def edu_grades(
    term: str | None = Query(default=None, max_length=16),
    user: CurrentUser = Depends(require_roles("student")),
    svc: EduService = Depends(get_edu_service),
) -> dict:
    return envelope(0, "ok", await svc.grades(user.id, term))


@router.get("/credits", summary="学分与绩点汇总")
async def edu_credits(
    user: CurrentUser = Depends(require_roles("student")),
    svc: EduService = Depends(get_edu_service),
) -> dict:
    return envelope(0, "ok", await svc.credits(user.id))
