from neo4j import GraphDatabase
from assistant_backend_1.config import NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

# Generic relation words that are NOT real names — skip as entity nodes
# These go in memory_summary only, not as named entity nodes
GENERIC_WORDS = {
    "son", "daughter", "mom", "dad", "mother", "father", "sister", "brother",
    "friend", "colleague", "boss", "doctor", "therapist", "teacher", "neighbor",
    "husband", "wife", "partner", "grandfather", "grandmother", "uncle", "aunt",
    "cousin", "nephew", "niece", "manager", "coworker", "classmate", "neighbor",
    "dentist", "psychiatrist", "counselor", "nurse", "tutor", "coach", "mentor"
}

# Dynamic relationship types based on entity type
# Instead of everything being KNOWS, each type gets its own relationship
ENTITY_RELATIONSHIPS = {
    "person":       "KNOWS",
    "place":        "VISITS_OR_LIVES_IN",
    "organization": "AFFILIATED_WITH",
    "health":       "HAS_OR_TAKES",
    "event":        "ATTENDED_OR_PLANS",
    "habit":        "HAS_HABIT",
    "emotion":      "EXPERIENCES",
    "interest":     "INTERESTED_IN",
    "goal":         "WANTS",
    "project":      "WORKING_ON",
    "pattern":      "HAS_PATTERN",
}

# Default relationship if type is unknown or not in the map
DEFAULT_RELATIONSHIP = "ASSOCIATED_WITH"


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

    Hierarchy:
    - Memory node is created and linked to User via REMEMBERS
    - If entity has a real proper name → Entity node is created/merged
    - Memory is also linked TO that Entity via ASSOCIATED_WITH
    - This creates a hierarchy: User → Entity → Memories about that entity

    Entity creation:
    - Always create entity if real name detected, even if relation is unknown
    - Never overwrite an existing relation with null/empty
    - Use dynamic relationship type based on entity type

    Result in Neo4j:
    (User)-[:REMEMBERS]──────────────────────►(Memory)
    (User)-[:KNOWS/VISITS/etc]──►(Entity)
                                      └──[:ASSOCIATED_WITH]──►(Memory)
    """
    with get_session() as session:
        # Ensure user node exists
        session.run(
            "MERGE (u:User {chat_id: $chat_id})",
            chat_id=chat_id
        )

        # Create memory node linked to user — this is always the core
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

        # Process entities — create nodes and link memories to them
        for entity in entities:
            name = (entity.get("name") or "").strip()
            entity_type = entity.get("type", "person").lower()
            relation = entity.get("relation", "")

            # Skip empty names and generic relation words
            if not name:
                continue
            if name.lower() in GENERIC_WORDS:
                continue

            # Get the right relationship type for this entity
            relationship = ENTITY_RELATIONSHIPS.get(
                entity_type, DEFAULT_RELATIONSHIP)

            # MERGE entity — create if new, find if exists
            # CASE WHEN: only update relation if a new non-empty one is provided
            # Never overwrite an existing relation with null/empty
            # This handles the "Aliza" case — first mention has no relation,
            # later mentions add the relation without losing earlier memories
            session.run(
                f"""
                MATCH (u:User {{chat_id: $chat_id}})
                MERGE (e:Entity {{name: $name, chat_id: $chat_id}})
                SET e.type = $type,
                    e.relation = CASE
                        WHEN $relation IS NOT NULL AND $relation <> ''
                        THEN $relation
                        ELSE coalesce(e.relation, '')
                    END,
                    e.updated_at = datetime()
                MERGE (u)-[:{relationship}]->(e)
                WITH e
                MATCH (m:Memory) WHERE elementId(m) = $memory_id
                MERGE (e)-[:ASSOCIATED_WITH]->(m)
                """,
                chat_id=chat_id,
                name=name,
                type=entity_type,
                relation=relation,
                memory_id=memory_node_id
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


def mark_task_pending(chat_id: str, title: str):
    """Revert a task back to pending (undo an accidental mark-done)."""
    with get_session() as session:
        session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:CREATED]->(t:Task)
            WHERE toLower(t.title) CONTAINS toLower($title)
            SET t.status = 'pending', t.completed_at = null
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
            WHERE (r.is_sent = false OR r.is_sent IS NULL)
            AND toLower(r.text) CONTAINS toLower($text)
            SET r.is_sent = true, r.completed_at = datetime()
            """,
            chat_id=chat_id,
            text=text
        )


def update_entity(chat_id: str, entities: list):
    """
    Update existing named entity nodes.
    Used for update_memory intent — when user corrects something.
    e.g. 'actually Elena is my niece not my daughter'
    """
    with get_session() as session:
        for entity in entities:
            name = (entity.get("name") or "").strip()
            if not name or name.lower() in GENERIC_WORDS:
                continue

            entity_type = entity.get("type", "person").lower()
            relation = entity.get("relation", "")
            relationship = ENTITY_RELATIONSHIPS.get(
                entity_type, DEFAULT_RELATIONSHIP)

            # Update entity properties
            # Also update the relationship type if entity type changed
            session.run(
                f"""
                MATCH (u:User {{chat_id: $chat_id}})-[old_rel]->(e:Entity {{name: $name, chat_id: $chat_id}})
                SET e.relation = $relation,
                    e.type = $type,
                    e.updated_at = datetime()
                DELETE old_rel
                WITH u, e
                MERGE (u)-[:{relationship}]->(e)
                """,
                chat_id=chat_id,
                name=name,
                type=entity_type,
                relation=relation
            )


# ─── Query Functions ───────────────────────────────────────────────

def get_user_context(chat_id: str) -> str:

    with get_session() as session:
        result = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})
            OPTIONAL MATCH (u)-[:REMEMBERS]->(m:Memory)
            OPTIONAL MATCH (u)-[er]->(e:Entity {chat_id: $chat_id})
            OPTIONAL MATCH (u)-[:CREATED]->(t:Task {status: 'pending'})
            OPTIONAL MATCH (u)-[:SET]->(r:Reminder)
            WHERE r.is_sent = false OR r.is_sent IS NULL
            OPTIONAL MATCH (u)-[:TRACKED]->(log:HabitLog)-[:OF]->(h:Habit)
            RETURN
                collect(DISTINCT m.summary)[0..30] as memories,
                collect(DISTINCT {name: e.name, type: e.type, relation: e.relation})[0..20] as entities,
                collect(DISTINCT {title: t.title, due: t.due})[0..10] as tasks,
                collect(DISTINCT {text: r.text, remind_at: r.remind_at})[0..5] as reminders,
                collect(DISTINCT {name: h.name, value: log.value})[0..5] as habits
            """,
            chat_id=chat_id
        )

        record = result.single()
        if not record:
            return "No previous information about this user yet."

        lines = []

        # ── Memories ──
        memories = [m for m in record["memories"] if m]
        if memories:
            lines.append("Things this user has shared:")
            lines.extend([f"  - {s}" for s in memories])

        # ── Entities split by type ──
        entities = [e for e in record["entities"] if e and e.get("name")]

        people = [e for e in entities if e.get("type") == "person"]
        if people:
            lines.append("People this user knows:")
            for e in people:
                if e.get("relation"):
                    lines.append(f"  - {e['name']} is their {e['relation']}")
                else:
                    lines.append(f"  - {e['name']} (relationship unknown)")

        places = [e for e in entities if e.get("type") == "place"]
        if places:
            lines.append("Places:")
            for e in places:
                rel = f" ({e['relation']})" if e.get("relation") else ""
                lines.append(f"  - {e['name']}{rel}")

        health = [e for e in entities if e.get("type") == "health"]
        if health:
            lines.append("Health information:")
            for e in health:
                rel = f" ({e['relation']})" if e.get("relation") else ""
                lines.append(f"  - {e['name']}{rel}")

        interests = [e for e in entities if e.get(
            "type") in ["interest", "goal"]]
        if interests:
            lines.append("Interests and goals:")
            for e in interests:
                label = "Goal" if e.get("type") == "goal" else "Interest"
                lines.append(f"  - {label}: {e['name']}")

        orgs = [e for e in entities if e.get("type") == "organization"]
        if orgs:
            lines.append("Organizations:")
            for e in orgs:
                rel = f" ({e['relation']})" if e.get("relation") else ""
                lines.append(f"  - {e['name']}{rel}")

        # ── Pending tasks ──
        tasks = [t for t in record["tasks"] if t and t.get("title")]
        if tasks:
            lines.append("Pending tasks:")
            for t in tasks:
                due = f" (due: {t['due']})" if t.get("due") else ""
                lines.append(f"  - {t['title']}{due}")

        # ── Reminders ──
        reminders = [r for r in record["reminders"] if r and r.get("text")]
        if reminders:
            lines.append("Reminders:")
            for r in reminders:
                time = f" at {r['remind_at']}" if r.get("remind_at") else ""
                lines.append(f"  - {r['text']}{time}")

        # ── Habits ──
        habits = [h for h in record["habits"] if h and h.get("name")]
        if habits:
            lines.append("Recent habits:")
            for h in habits:
                lines.append(f"  - {h['name']}: {h['value']}")

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
            RETURN u.chat_id as chat_id, elementId(r) as node_id,
                   r.text as text, r.remind_at as remind_at
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
            RETURN elementId(r) as id, r.text as name,
                   r.remind_at as due_datetime, r.is_sent as is_sent
            ORDER BY r.remind_at ASC
            """,
            chat_id=chat_id
        )
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


def get_all_tasks(chat_id: str) -> list:
    """Read all pending tasks from Neo4j for this user."""
    with get_session() as session:
        result = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:CREATED]->(t:Task)
            WHERE t.status = 'pending'
            RETURN elementId(t) as id, t.title as title, t.due as due
            ORDER BY t.created_at ASC
            """,
            chat_id=chat_id
        )
        return [{"id": r["id"], "title": r["title"], "due": r["due"]} for r in result]


def update_local_task(chat_id: str, node_id: str, title: str = None, due: str = None) -> bool:
    """Update title and/or due date for an existing task."""
    with get_session() as session:
        sets = []
        params = {"node_id": node_id, "chat_id": chat_id}
        if title is not None:
            sets.append("t.title = $title")
            params["title"] = title
        if due is not None:
            sets.append("t.due = $due")
            params["due"] = due

        if not sets:
            return True

        query = f"""
        MATCH (u:User {{chat_id: $chat_id}})-[:CREATED]->(t:Task)
        WHERE elementId(t) = $node_id
        SET {', '.join(sets)}
        RETURN elementId(t) as node_id
        """
        result = session.run(query, **params)
        return result.single() is not None


def delete_local_task(chat_id: str, node_id: str) -> bool:
    """Delete a task from Neo4j."""
    with get_session() as session:
        result = session.run(
            """
            MATCH (u:User {chat_id: $chat_id})-[:CREATED]->(t:Task)
            WHERE elementId(t) = $node_id
            DETACH DELETE t
            RETURN count(t) as deleted_count
            """,
            chat_id=chat_id,
            node_id=node_id
        )
        record = result.single()
        return record is not None and record["deleted_count"] > 0
