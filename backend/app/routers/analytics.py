"""Router for analytics endpoints."""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlmodel import select, func, case, col
from sqlmodel.ext.asyncio.session import AsyncSession
from datetime import date

# Импорты твоих модулей
from ..database import get_session
from ..models.item import ItemRecord as Item
from ..models.learner import Learner
from ..models.interaction import InteractionLog
from ..auth import get_api_key  # Импортируем защиту

# ОДНО объявление роутера с зависимостью для всего файла
router = APIRouter(dependencies=[Depends(get_api_key)])

# Дальше идет твой код функций...


    """Вспомогательная функция для поиска ID всех заданий конкретной лабы."""
    # Превращаем "lab-04" в "Lab 04" для поиска по заголовку
    lab_title_part = lab_param.replace("-", " ").title()
    
    # 1. Ищем саму лабу
    lab_stmt = select(Item).where(col(Item.title).contains(lab_title_part), Item.type == "lab")
    lab = (await session.exec(lab_stmt)).first()
    if not lab:
        return []

    # 2. Ищем все дочерние задания (tasks)
    tasks_stmt = select(Item.id).where(Item.parent_id == lab.id)
    task_ids = (await session.exec(tasks_stmt)).all()
    return task_ids

@router.get("/scores")
async def get_scores(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    task_ids = await get_lab_task_ids(lab, session)
    if not task_ids:
        return [
            {"bucket": "0-25", "count": 0},
            {"bucket": "26-50", "count": 0},
            {"bucket": "51-75", "count": 0},
            {"bucket": "76-100", "count": 0}
        ]

    # Группируем баллы по корзинам через CASE WHEN
    score_bucket = case(
        (InteractionLog.score <= 25, "0-25"),
        (InteractionLog.score <= 50, "26-50"),
        (InteractionLog.score <= 75, "51-75"),
        else_="76-100"
    ).label("bucket")

    stmt = (
        select(score_bucket, func.count(InteractionLog.id).label("count"))
        .where(InteractionLog.item_id.in_(task_ids))
        .group_by("bucket")
    )
    results = (await session.exec(stmt)).all()
    
    # Формируем итоговый список, гарантируя наличие всех 4 корзин
    buckets = {"0-25": 0, "26-50": 0, "51-75": 0, "76-100": 0}
    for row in results:
        buckets[row.bucket] = row.count

    return [{"bucket": b, "count": c} for b, c in buckets.items()]

@router.get("/pass-rates")
async def get_pass_rates(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    # Ищем лабу и ее таски, чтобы считать статистику по каждому
    lab_title_part = lab.replace("-", " ").title()
    lab_stmt = select(Item).where(col(Item.title).contains(lab_title_part), Item.type == "lab")
    lab_obj = (await session.exec(lab_stmt)).first()
    
    if not lab_obj:
        return []

    stmt = (
        select(
            Item.title.label("task"),
            func.round(func.avg(InteractionLog.score), 1).label("avg_score"),
            func.count(InteractionLog.id).label("attempts")
        )
        .join(InteractionLog, InteractionLog.item_id == Item.id)
        .where(Item.parent_id == lab_obj.id)
        .group_by(Item.title)
        .order_by(Item.title)
    )
    results = (await session.exec(stmt)).all()
    return [
    {"task": row.task, "avg_score": row.avg_score, "attempts": row.attempts} 
    for row in results
]

@router.get("/timeline")
async def get_timeline(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    task_ids = await get_lab_task_ids(lab, session)
    if not task_ids:
        return []

    # Группируем по дате (приводим создано_в к дате)
    stmt = (
        select(
            func.date(InteractionLog.created_at).label("date"),
            func.count(InteractionLog.id).label("submissions")
        )
        .where(InteractionLog.item_id.in_(task_ids))
        .group_by(func.date(InteractionLog.created_at))
        .order_by(func.date(InteractionLog.created_at))
    )
    results = (await session.exec(stmt)).all()
    # Превращаем объекты date в строки YYYY-MM-DD
    return [{"date": str(row.date), "submissions": row.submissions} for row in results]

@router.get("/groups")
async def get_groups(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    task_ids = await get_lab_task_ids(lab, session)
    if not task_ids:
        return []

    stmt = (
        select(
            Learner.student_group.label("group"),
            func.round(func.avg(InteractionLog.score), 1).label("avg_score"),
            func.count(func.distinct(InteractionLog.learner_id)).label("students")
        )
        .join(InteractionLog, InteractionLog.learner_id == Learner.id)
        .where(InteractionLog.item_id.in_(task_ids))
        .group_by(Learner.student_group)
        .order_by(Learner.student_group)
    )
    results = (await session.exec(stmt)).all()
    return [
    {"group": row.group, "avg_score": row.avg_score, "students": row.students} 
    for row in results
]