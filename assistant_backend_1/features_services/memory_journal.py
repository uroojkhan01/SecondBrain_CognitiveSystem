from neo4j import GraphDatabase
from assistant_backend_1.config import NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))


def get_session():
    return driver.session()


# ─── Save Functions ───────────────────────────────────────────────

def save_memory(chat_id: str, summary: str, entities: list) -> str:
    with get_session() as session:
        session.run(
            "MERGE (u:User {chat_id: $chat_id})",
            chat_id=chat_id
        )

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

        for entity in entities:
            session.run(
                """
                MATCH (u:User {chat_id: $chat_id})
                MERGE (e:Entity {name: $name, type: $type, chat_id: $chat_id})
                SET e.relation = $relation
                MERGE (u)-[:KNOWS]->(e)
                """,
                chat_id=chat_id,
                name=entity.get("name"),
                type=entity.get("type"),
                relation=entity.get("relation")
            )

        return memory_node_id


def save_reminder(chat_id: str, text: str, remind_at: str) -> str:
    with get_session() as session:
        session.run(
            "MERGE (u:User {chat_id: $chat_id})",
            chat_id=chat_id
        )
        result = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})
            CREATE (r:Reminder {text: $text, remind_at: $remind_at, created_at: datetime()})
            CREATE (u)-[:SET]->(r)
            RETURN elementId(r) as node_id
            """,
            chat_id=chat_id,
            text=text,
            remind_at=remind_at
        )
        return result.single()["node_id"]


def save_task(chat_id: str, title: str, due: str) -> str:
    with get_session() as session:
        session.run(
            "MERGE (u:User {chat_id: $chat_id})",
            chat_id=chat_id
        )
        result = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})
            CREATE (t:Task {title: $title, due: $due, status: 'pending', created_at: datetime()})
            CREATE (u)-[:CREATED]->(t)
            RETURN elementId(t) as node_id
            """,
            chat_id=chat_id,
            title=title,
            due=due
        )
        return result.single()["node_id"]


def save_habit(chat_id: str, name: str, value: str) -> str:
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


def update_entity(chat_id: str, entities: list):
    with get_session() as session:
        for entity in entities:
            session.run(
                """
                MATCH (u:User {chat_id: $chat_id})-[:KNOWS]->(e:Entity {name: $name, chat_id: $chat_id})
                SET e.relation = $relation, e.type = $type, e.updated_at = datetime()
                """,
                chat_id=chat_id,
                name=entity.get("name"),
                type=entity.get("type"),
                relation=entity.get("relation")
            )


# ─── Query Functions ───────────────────────────────────────────────

def get_user_context(chat_id: str) -> str:
    with get_session() as session:
        lines = []

        entities = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:KNOWS]->(e:Entity {chat_id: $chat_id})
            RETURN e.name as name, e.type as type, e.relation as relation
            """,
            chat_id=chat_id
        )
        for record in entities:
            name = record["name"]
            relation = record["relation"]
            etype = record["type"]
            if relation:
                lines.append(f"- {name} is this user's {relation} ({etype})")
            else:
                lines.append(f"- {name} ({etype}) was mentioned by this user")

        memories = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:REMEMBERS]->(m:Memory)
            RETURN m.summary as summary
            ORDER BY m.created_at DESC
            LIMIT 10
            """,
            chat_id=chat_id
        )
        for record in memories:
            lines.append(f"- {record['summary']}")

        reminders = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:SET]->(r:Reminder)
            RETURN r.text as text, r.remind_at as remind_at
            ORDER BY r.created_at DESC
            LIMIT 5
            """,
            chat_id=chat_id
        )
        for record in reminders:
            lines.append(
                f"- Reminder: {record['text']} at {record['remind_at']}")

        tasks = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:CREATED]->(t:Task {status: 'pending'})
            RETURN t.title as title, t.due as due
            ORDER BY t.created_at DESC
            LIMIT 5
            """,
            chat_id=chat_id
        )
        for record in tasks:
            lines.append(
                f"- Pending task: {record['title']} (due: {record['due']})")

        if not lines:
            return "No previous information about this user yet."

        return "\n".join(lines)
