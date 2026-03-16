import httpx
from datetime import datetime, timezone
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.settings import settings
from app.models.item import ItemRecord
from app.models.learner import Learner
from app.models.interaction import InteractionLog

# ---------------------------------------------------------------------------
# Extract — fetch data from the autochecker API
# ---------------------------------------------------------------------------

async def fetch_items() -> list[dict]:
    """Запрашиваем каталог лаб и тасок из API университета."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.autochecker_api_url}/api/items",
            auth=(settings.autochecker_email, settings.autochecker_password)
        )
        if response.status_code != 200:
            raise Exception(f"API Error: {response.status_code}")
        return response.json()

async def fetch_logs(since: datetime | None = None) -> list[dict]:
    """Запрашиваем логи чеков с поддержкой пагинации."""
    all_logs = []
    params = {"limit": 500}
    if since:
        params["since"] = since.isoformat()

    async with httpx.AsyncClient() as client:
        has_more = True
        while has_more:
            response = await client.get(
                f"{settings.autochecker_api_url}/api/logs",
                params=params,
                auth=(settings.autochecker_email, settings.autochecker_password)
            )
            data = response.json()
            page_logs = data.get("logs", [])
            all_logs.extend(page_logs)
            
            has_more = data.get("has_more", False)
            if has_more and page_logs:
                # Берем время последнего лога для следующей страницы
                params["since"] = page_logs[-1]["submitted_at"]
    
    return all_logs

# ---------------------------------------------------------------------------
# Load — insert fetched data into the local database
# ---------------------------------------------------------------------------

async def load_items(items: list[dict], session: AsyncSession) -> int:
    """Загружаем лабы и таски, сохраняя структуру дерева."""
    new_count = 0
    lab_map = {}  # Для связи task -> lab

    # 1. Сначала обрабатываем лабы
    for item in items:
        if item["type"] == "lab":
            # Проверяем, есть ли уже такая лаба
            existing = await session.exec(
                select(ItemRecord).where(ItemRecord.type == "lab", ItemRecord.title == item["title"])
            )
            lab_record = existing.first()
            if not lab_record:
                lab_record = ItemRecord(type="lab", title=item["title"])
                session.add(lab_record)
                new_count += 1
            lab_map[item["lab"]] = lab_record

    await session.flush() # Получаем ID лаб из базы

    # 2. Теперь обрабатываем таски
    for item in items:
        if item["type"] == "task":
            parent_lab = lab_map.get(item["lab"])
            if parent_lab:
                existing = await session.exec(
                    select(ItemRecord).where(
                        ItemRecord.type == "task", 
                        ItemRecord.title == item["title"],
                        ItemRecord.parent_id == parent_lab.id
                    )
                )
                if not existing.first():
                    task_record = ItemRecord(
                        type="task", 
                        title=item["title"], 
                        parent_id=parent_lab.id
                    )
                    session.add(task_record)
                    new_count += 1

    await session.commit()
    return new_count

async def load_logs(logs: list[dict], items_catalog: list[dict], session: AsyncSession) -> int:
    """Загружаем взаимодействия и создаем студентов."""
    new_count = 0
    
    # Маппинг коротких ID в названия из базы
    lookup = {}
    for it in items_catalog:
        key = (it["lab"], it.get("task"))
        lookup[key] = it["title"]

    for log in logs:
        # 1. Находим или создаем студента
        learner_stmt = select(Learner).where(Learner.external_id == log["student_id"])
        learner = (await session.exec(learner_stmt)).first()
        if not learner:
            learner = Learner(external_id=log["student_id"], student_group=log["group"])
            session.add(learner)
            await session.flush()

        # 2. Находим соответствующий Item в базе
        item_title = lookup.get((log["lab"], log["task"]))
        if not item_title: continue
        
        item_stmt = select(ItemRecord).where(ItemRecord.title == item_title)
        item = (await session.exec(item_stmt)).first()
        if not item: continue

        # 3. Идемпотентность: проверяем, нет ли уже такого лога
        log_exists = await session.exec(
            select(InteractionLog).where(InteractionLog.external_id == log["id"])
        )
        if log_exists.first(): continue

        # 4. Создаем запись о попытке
        interaction = InteractionLog(
            external_id=log["id"],
            learner_id=learner.id,
            item_id=item.id,
            kind="attempt",
            score=log["score"],
            checks_passed=log["passed"],
            checks_total=log["total"],
            created_at=datetime.fromisoformat(log["submitted_at"].replace("Z", "+00:00")).replace(tzinfo=None)
        )
        session.add(interaction)
        new_count += 1

    await session.commit()
    return new_count

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def sync(session: AsyncSession) -> dict:
    """Запуск всего пайплайна."""
    # 1. Загружаем каталог предметов
    raw_items = await fetch_items()
    await load_items(raw_items, session)

    # 2. Находим время последней синхронизации
    last_log_stmt = select(func.max(InteractionLog.created_at))
    last_ts = (await session.exec(last_log_stmt)).first()

    # 3. Качаем и грузим новые логи
    raw_logs = await fetch_logs(since=last_ts)
    new_records = await load_logs(raw_logs, raw_items, session)

    # 4. Считаем общее количество записей
    total_records = (await session.exec(select(func.count(InteractionLog.id)))).first()

    return {"new_records": new_records, "total_records": total_records}