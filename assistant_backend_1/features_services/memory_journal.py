from neo4j import GraphDatabase
from assistant_backend_1.config import NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

# Generic relation words that are NOT real names — skip as entity nodes
GENERIC_WORDS = {
    "son", "daughter", "mom", "dad", "mother", "father", "sister", "brother",
    "friend", "colleague", "boss", "doctor", "therapist", "teacher", "neighbor",
    "husband", "wife", "partner", "grandfather", "grandmother", "uncle", "aunt",
    "cousin", "nephew", "niece", "manager", "coworker", "classmate"
}


def get_session():
    return driver.session()


# ─── User ─────────────────────────────────────────────────────────

def save_or_update_user(chat_id: str, first_name: str, username: str):
    """Create or update user node with Telegram info."""
    with get_session() as session:
        session.run(
            """
            MERGE (u:User {chat_id: $chat_id})
            SET u.first_name = $first_name,
                u.username = $username,
                u.updated_at = datetime()
            """,
            chat_id=chat_id,
            first_name=first_name or "",
            username=username or ""
        )


# ─── Save Functions ───────────────────────────────────────────────

def save_memory(chat_id: str, summary: str, entities: list) -> str:
    """
    Save a rich memory summary as the main memory node.
    Entities are only saved if they have real proper names.
    The summary is what the LLM reads to answer questions.
    """
    with get_session() as session:
        session.run(
            "MERGE (u:User {chat_id: $chat_id})",
            chat_id=chat_id
        )

        # Save the full memory summary — this is the core
        result = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})
            CREATE (m:Memory {summary: $summary, created_at: datetime()})
            CREATE (u)-[:REMEMBERS]->(m)
            RETURN elementId(m) as node_id
            """,
            chat_id=chat_id,
            summary=summary
        )
        memory_node_id = result.single()["node_id"]

        # Save entities only if they have real proper names
        for entity in entities:
            name = entity.get("name", "").strip()
            if not name:
                continue
            if name.lower() in GENERIC_WORDS:
                continue  # skip generic relation words

            session.run(
                """
                MATCH (u:User {chat_id: $chat_id})
                MERGE (e:Entity {name: $name, chat_id: $chat_id})
                SET e.type = $type,
                    e.relation = $relation,
                    e.updated_at = datetime()
                MERGE (u)-[:KNOWS]->(e)
                """,
                chat_id=chat_id,
                name=name,
                type=entity.get("type", "person"),
                relation=entity.get("relation", "")
            )

        return memory_node_id


def save_reminder(chat_id: str, text: str, remind_at: str) -> str:
    """Save a reminder node linked to the user."""
    with get_session() as session:
        session.run(
            "MERGE (u:User {chat_id: $chat_id})",
            chat_id=chat_id
        )
        result = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})
            CREATE (r:Reminder {
                text: $text,
                remind_at: $remind_at,
                is_sent: false,
                created_at: datetime()
            })
            CREATE (u)-[:SET]->(r)
            RETURN elementId(r) as node_id
            """,
            chat_id=chat_id,
            text=text,
            remind_at=remind_at
        )
        return result.single()["node_id"]


def save_task(chat_id: str, title: str, due: str) -> str:
    """Save a task node linked to the user."""
    with get_session() as session:
        session.run(
            "MERGE (u:User {chat_id: $chat_id})",
            chat_id=chat_id
        )
        result = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})
            CREATE (t:Task {
                title: $title,
                due: $due,
                status: 'pending',
                created_at: datetime()
            })
            CREATE (u)-[:CREATED]->(t)
            RETURN elementId(t) as node_id
            """,
            chat_id=chat_id,
            title=title,
            due=due
        )
        return result.single()["node_id"]


def save_habit(chat_id: str, name: str, value: str) -> str:
    """Save a habit log node linked to the user."""
    with get_session() as session:
        session.run(
            "MERGE (u:User {chat_id: $chat_id})",
            chat_id=chat_id
        )
        result = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})
            MERGE (h:Habit {name: $name, chat_id: $chat_id})
            CREATE (log:HabitLog {value: $value, logged_at: datetime()})
            CREATE (u)-[:TRACKED]->(log)
            CREATE (log)-[:OF]->(h)
            RETURN elementId(log) as node_id
            """,
            chat_id=chat_id,
            name=name,
            value=value
        )
        return result.single()["node_id"]


def mark_task_done(chat_id: str, title: str):
    """Mark a matching task as done."""
    with get_session() as session:
        session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:CREATED]->(t:Task)
            WHERE toLower(t.title) CONTAINS toLower($title)
            SET t.status = 'done', t.completed_at = datetime()
            """,
            chat_id=chat_id,
            title=title
        )


def mark_reminder_done(chat_id: str, text: str):
    """Mark a matching reminder as sent/done in Neo4j."""
    with get_session() as session:
        session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:SET]->(r:Reminder)
            WHERE (r.is_sent = false OR r.is_sent IS NULL) AND toLower(r.text) CONTAINS toLower($text)
            SET r.is_sent = true, r.completed_at = datetime()
            """,
            chat_id=chat_id,
            text=text
        )


def update_entity(chat_id: str, entities: list):
    """Update existing named entity nodes."""
    with get_session() as session:
        for entity in entities:
            name = entity.get("name", "").strip()
            if not name or name.lower() in GENERIC_WORDS:
                continue
            session.run(
                """
                MATCH (u:User {chat_id: $chat_id})-[:KNOWS]->(e:Entity {name: $name, chat_id: $chat_id})
                SET e.relation = $relation,
                    e.type = $type,
                    e.updated_at = datetime()
                """,
                chat_id=chat_id,
                name=name,
                type=entity.get("type"),
                relation=entity.get("relation")
            )


# ─── Query Functions ───────────────────────────────────────────────

def get_user_context(chat_id: str) -> str:
    """
    Pull everything known about this user as plain text.
    Injected into LLM prompt so it can answer naturally.
    The LLM does the reasoning — we just feed it the facts.
    """
    with get_session() as session:
        lines = []

        # ── Memories (most important — rich plain text summaries) ──
        memories = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:REMEMBERS]->(m:Memory)
            RETURN m.summary as summary
            ORDER BY m.created_at DESC
            LIMIT 30
            """,
            chat_id=chat_id
        )
        memory_lines = [r["summary"] for r in memories]
        if memory_lines:
            lines.append("Things this user has shared:")
            lines.extend([f"  - {s}" for s in memory_lines])

        # ── Named entities (only real proper names) ──
        entities = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:KNOWS]->(e:Entity {chat_id: $chat_id})
            RETURN e.name as name, e.type as type, e.relation as relation
            """,
            chat_id=chat_id
        )
        entity_lines = []
        for r in entities:
            if r["relation"]:
                entity_lines.append(
                    f"  - {r['name']} is their {r['relation']}")
            else:
                entity_lines.append(f"  - {r['name']} was mentioned")
        if entity_lines:
            lines.append("People and places this user knows:")
            lines.extend(entity_lines)

        # ── Pending tasks ──
        tasks = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:CREATED]->(t:Task {status: 'pending'})
            RETURN t.title as title, t.due as due
            ORDER BY t.created_at DESC
            LIMIT 10
            """,
            chat_id=chat_id
        )
        task_lines = []
        for r in tasks:
            due = f" (due: {r['due']})" if r["due"] else ""
            task_lines.append(f"  - {r['title']}{due}")
        if task_lines:
            lines.append("Pending tasks:")
            lines.extend(task_lines)

        # ── Reminders ──
        reminders = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:SET]->(r:Reminder)
            WHERE r.is_sent = false OR r.is_sent IS NULL
            RETURN r.text as text, r.remind_at as remind_at
            ORDER BY r.created_at DESC
            LIMIT 5
            """,
            chat_id=chat_id
        )
        reminder_lines = []
        for r in reminders:
            time = f" at {r['remind_at']}" if r["remind_at"] else ""
            reminder_lines.append(f"  - {r['text']}{time}")
        if reminder_lines:
            lines.append("Reminders:")
            lines.extend(reminder_lines)

        # ── Habits ──
        habits = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:TRACKED]->(log:HabitLog)-[:OF]->(h:Habit)
            RETURN h.name as name, log.value as value, log.logged_at as logged_at
            ORDER BY log.logged_at DESC
            LIMIT 5
            """,
            chat_id=chat_id
        )
        habit_lines = []
        for r in habits:
            habit_lines.append(f"  - {r['name']}: {r['value']}")
        if habit_lines:
            lines.append("Recent habits tracked:")
            lines.extend(habit_lines)

        if not lines:
            return "No previous information about this user yet."

        return "\n".join(lines)


# =====================================================================
# NEO4J LOCAL REMINDER HELPERS
# =====================================================================

def get_due_reminders() -> list:
    """Fetch all reminders that have not been sent yet."""
    with get_session() as session:
        result = session.run(
            """
            MATCH (u:User)-[:SET]->(r:Reminder {is_sent: false})
            RETURN u.chat_id as chat_id, elementId(r) as node_id, r.text as text, r.remind_at as remind_at
            """
        )
        return [dict(record) for record in result]


def mark_reminder_sent(node_id: str):
    """Mark a reminder as sent in Neo4j."""
    with get_session() as session:
        session.run(
            """
            MATCH (r:Reminder)
            WHERE elementId(r) = $node_id
            SET r.is_sent = true, r.sent_at = datetime()
            """,
            node_id=node_id
        )


def get_local_reminders(chat_id: str) -> list:
    """Read all reminders from Neo4j for this user."""
    with get_session() as session:
        result = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:SET]->(r:Reminder)
            RETURN elementId(r) as id, r.text as name, r.remind_at as due_datetime, r.is_sent as is_sent
            ORDER BY r.remind_at ASC
            """,
            chat_id=chat_id
        )
        # Adapt format for reminders.py compatibility
        reminders = []
        for record in result:
            due_str = record["due_datetime"]
            due_datetime = None
            has_time = False
            if due_str:
                try:
                    if "T" in due_str:
                        from datetime import datetime
                        due_datetime = datetime.fromisoformat(due_str)
                        has_time = True
                    else:
                        from datetime import datetime
                        due_datetime = datetime.strptime(due_str, "%Y-%m-%d")
                        has_time = False
                except Exception:
                    due_datetime = due_str
            reminders.append({
                "id": record["id"],
                "name": record["name"],
                "due_datetime": due_datetime,
                "has_time": has_time,
                "is_sent": record["is_sent"]
            })
        return reminders


def update_local_reminder(chat_id: str, node_id: str, text: str = None, remind_at: str = None) -> bool:
    """Update text and/or remind_at for an existing local reminder."""
    with get_session() as session:
        # Build query dynamic properties update
        sets = []
        params = {"node_id": node_id, "chat_id": chat_id}
        if text is not None:
            sets.append("r.text = $text")
            params["text"] = text
        if remind_at is not None:
            sets.append("r.remind_at = $remind_at")
            params["remind_at"] = remind_at
            
        if not sets:
            return True
            
        query = f"""
        MATCH (u:User {{chat_id: $chat_id}})-[:SET]->(r:Reminder)
        WHERE elementId(r) = $node_id
        SET {', '.join(sets)}
        RETURN elementId(r) as node_id
        """
        result = session.run(query, **params)
        return result.single() is not None


def delete_local_reminder(chat_id: str, node_id: str) -> bool:
    """Delete a reminder from Neo4j."""
    with get_session() as session:
        result = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:SET]->(r:Reminder)
            WHERE elementId(r) = $node_id
            DETACH DELETE r
            RETURN count(r) as deleted_count
            """,
            chat_id=chat_id,
            node_id=node_id
        )
        record = result.single()
        return record is not None and record["deleted_count"] > 0

