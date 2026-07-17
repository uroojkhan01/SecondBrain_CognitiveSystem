# 🧠 Second Brain

A production-grade, multi-agent AI system that acts as an external cognitive layer for people with ADHD — capturing thoughts, organising tasks, tracking memory, and sending proactive reminders, all through Telegram.

**Status:** ✅ Fully Deployed & Operational  
**Bot:** [@secondbrain01_bot](https://t.me/secondbrain01_bot)  
**Repo:** [github.com/uroojkhan01/SecondBrain_CognitiveSystem](https://github.com/uroojkhan01/SecondBrain_CognitiveSystem)  
**Course:** Large Language Models — Final Project, Freie Universität Berlin  
**Instructor:** Tim Landgraf

---

## What is it?

Second Brain is a fully deployed cognitive assistant that accepts text and voice input via Telegram and autonomously manages the user's tasks, reminders, memories, and knowledge across three persistent data layers — Neo4j, PostgreSQL, and Notion. The user never has to open Notion, sort a task, or remember to check anything. The system handles all of it in the background.

What began as a scoped MVP with basic Notion CRUD and a single agent was delivered as a complete cognitive ecosystem: two distinct AI agents, four background automation jobs, a dual-LLM setup with automatic fallback, full Notion OAuth with eight auto-created databases, and a cross-referenced data architecture linking every record across all three storage systems.

---

## The problem it solves

People with ADHD face a specific set of challenges that most productivity tools make worse, not better:

**Working memory fails constantly** — by the time you open an app, find the right field, and type, the thought is gone. Second Brain accepts a raw voice note in seconds and handles everything else automatically.

**Traditional tools require executive function to use** — you have to categorise, prioritise, and organise manually. That's exactly what ADHD makes hard. Second Brain has a dedicated AI Task Agent that runs every 30 minutes and does all of that automatically, without the user doing anything.

**Time blindness is real** — people with ADHD don't feel time passing. Passive reminders in a list don't work. Second Brain proactively sends Telegram alerts at the exact right moment, checks every 5 minutes, and never misses a due reminder.

**Context switching is expensive** — every app you have to open is friction that breaks focus. Second Brain lives entirely in Telegram. You never leave the chat.

**Working memory is unreliable across days** — you tell someone your doctor's name today and forget it by Thursday. Second Brain stores everything you tell it in a Neo4j knowledge graph and injects that context into every future conversation. It always knows who Dr. Patel is, what your sister's allergy is, and what you were stressed about last week.

**ADHD brains think in chaotic bursts, not neat bullet points** — send "I need to call mom, remind me dentist Friday, book flights before September, and I think I left my charger at work" and Second Brain extracts each item individually, classifies it correctly, and saves everything to the right place.

---

## What makes it technically impressive

This system went significantly beyond the original project scope:

| Feature | Original Plan | What was delivered |
|---|---|---|
| LLM setup | Single Groq key | Dual-LLM: up to 5 Groq keys rotated sequentially → automatic Claude fallback, zero downtime |
| Memory / RAG | "Could-have" vector DB | Full Neo4j knowledge graph — 5 node types, relationship-aware context injected into every LLM prompt |
| Notion integration | Basic CRUD | Full OAuth 2.0 + 8 databases auto-created on first login with cross-linked relation properties |
| Task organisation | Manual | Autonomous Task Agent — runs every 30 min, categorises tasks into 6 life areas, detects projects, generates AI summaries |
| Data architecture | Single store | Three fully cross-referenced stores — every record links PostgreSQL ID + Neo4j node ID + Notion page ID |
| Agents | 1 central agent | 2 agents: Conversation Agent (real-time) + Task Agent (scheduled, fully autonomous) |
| Background jobs | None planned | 4 automated jobs: reminder alerts, task organisation, progress bar sync, daily summary |
| Error handling | Basic | Fuzzy task/reminder matching, graceful Notion degradation, silent hook failures that never crash the bot |

---

## How it works

```
User sends text or voice message on Telegram
              ↓
FastAPI webhook receives the message
              ↓
Voice? → faster-whisper transcribes it locally
              ↓
Neo4j context fetched (memories, tasks, entities, reminders)
              ↓
Groq LLaMA 3.3-70b classifies intent + generates reply
(if all Groq keys exhausted → Claude Haiku/Sonnet takes over automatically)
              ↓
Intent routed → saved to Neo4j + PostgreSQL + Notion simultaneously
              ↓
Reply sent to user
              ↓
Background scheduler runs independently every 5–30 min:
reminders fired · tasks organised · progress updated · daily summary sent
```

---

## Architecture

### Two AI Agents

**Conversation Agent** — processes every Telegram message in real time. Receives a system prompt enriched with the user's full Neo4j context and last 20 conversation turns. Returns structured JSON with intent, reply, entities, memory summary, task, and reminder fields.

**Task Agent** — fully autonomous, runs every 30 minutes independent of user messages. Reads all unorganised tasks from Notion, sends them to the LLM for categorisation, creates entries in the correct Life Area database with AI-generated executive summaries, detects projects (5+ related tasks), links them to Master Projects DB, and marks tasks as organised.

### Dual-LLM Fallback

```
Request → Groq key 1 → Groq key 2 → ... → Groq key 5 → Claude Haiku/Sonnet
```

Fully transparent to the user. If all Groq keys hit rate limits simultaneously, Claude takes over with no change in behaviour or response format.

### Four Background Jobs

| Job | Interval | What it does |
|---|---|---|
| Reminder check | Every 5 min | Queries Neo4j for due reminders → sends Telegram alert → marks as sent |
| Task organiser | Every 30 min | Task Agent runs → LLM categorises tasks → creates Area DB entries + project links |
| Progress sync | Every 10 min | Counts completed tasks per project → updates Progress Bar % in Master Projects |
| Daily summary | 22:00 Berlin | Generates personalised daily digest → sends to every user's Telegram |

---

## Data layer

Three stores, fully cross-referenced on every record:

### PostgreSQL — Relational store (source of truth)

Designed with SQLAlchemy, migrated with Alembic, hosted on DigitalOcean Managed Postgres.

| Table | Key columns |
|---|---|
| users | chat_id · first_name · notion_access_token · notion_connected |
| messages | user_id · raw_input · input_type · intent · llm_raw_response |
| tasks | user_id · title · due_date · status · notion_page_id · neo4j_node_id |
| reminders | user_id · text · remind_at · is_sent · neo4j_node_id |
| voice_messages | message_id · telegram_file_id · transcription |
| notion_databases | user_id · notion_db_id · name |

Every task and reminder stores its Notion page ID and Neo4j node ID — making cross-store queries and consistency checks possible at any time.

### Neo4j — Knowledge graph (long-term memory)

Full graph context is injected into every LLM system prompt, giving the Conversation Agent awareness of past interactions, named entities, relationships, and pending commitments across all previous sessions.

```
(User) -[:REMEMBERS]→ (Memory)
(User) -[:KNOWS]→ (Entity) -[:ASSOCIATED_WITH]→ (Memory)
(User) -[:CREATED]→ (Task)
(User) -[:SET]→ (Reminder)
(User) -[:TRACKED]→ (HabitLog) -[:OF]→ (Habit)
```

### Notion — Visual workspace (8 auto-created databases)

The entire workspace is built programmatically on first OAuth login via `setup_second_brain()`. The user never has to create or configure anything manually.

| Database | Key properties |
|---|---|
| Tasks & To Dos | Task Name · Execution Date · Criticality (P1/P2/P3) · Parent Project · Organized · Done |
| Master Projects DB | Project Name · Status · Target Deadline · Progress Bar (0–100%) |
| Health & Fitness | Name · Date Logged · AI Executive Summary · Parent Task Link |
| Finance & Wealth | Name · Date Logged · AI Executive Summary · Parent Task Link |
| Career & Professional | Name · Date Logged · AI Executive Summary · Parent Task Link |
| Personal Growth & Learning | Name · Date Logged · AI Executive Summary · Parent Task Link |
| Home & Lifestyle | Name · Date Logged · AI Executive Summary · Parent Task Link |
| Family & Friends | Name · Date Logged · AI Executive Summary · Parent Task Link |

Relation chain: `Area DB entry → Task → Master Project` — fully linked across all 8 databases.

---

## Supported intents (15+)

| Intent | What happens |
|---|---|
| `create_task` | Saved to Neo4j + PostgreSQL + Notion Tasks & To Dos |
| `set_reminder` | Saved to Neo4j + PostgreSQL, alert fires at exact time |
| `save_memory` | Stored in Neo4j knowledge graph, injected into future prompts |
| `mark_done` | Task marked done across Neo4j + PostgreSQL + Notion, progress bar updated |
| `mark_undone` | Reopens a completed task across all stores |
| `update_task` | Updates title/due date/criticality in Neo4j + Notion |
| `update_reminder` | Reschedules or renames reminder across all stores |
| `delete_task` | Removes from Neo4j, archives in Notion, cancelled in PostgreSQL |
| `delete_reminder` | Removes from Neo4j + PostgreSQL, archives in Notion |
| `update_project` | Updates deadline or status in Master Projects DB |
| `update_memory` | Corrects a stored fact or entity in the knowledge graph |
| `brain_dump` | Extracts multiple intents from one message, saves each individually |
| `habit_track` | Logs habit value as HabitLog node in Neo4j |
| `seek_advice` | Conversational response, no save |
| `conversation` | General chat with full memory context |

---

## Tech stack

| Component | Technology |
|---|---|
| Backend | FastAPI (Python 3.11) |
| Deployment | DigitalOcean App Platform |
| Primary LLM | Groq — LLaMA 3.3-70b-versatile |
| Fallback LLM | Anthropic — Claude Haiku 4.5 / Sonnet 4.6 |
| Voice transcription | faster-whisper (runs locally on server) |
| Knowledge graph | Neo4j AuraDB |
| Relational DB | PostgreSQL — DigitalOcean Managed |
| ORM / Migrations | SQLAlchemy + Alembic |
| Visual workspace | Notion API (OAuth 2.0) |
| Background jobs | APScheduler (in-process, no Celery/Redis needed) |
| Interface | Telegram Bot API |

---

## Project structure

```
assistant_backend_1/
├── api/handlers/
│   ├── telegram_handler.py     # webhook, hook calls, /done and /organise commands
│   └── notion_handler.py       # OAuth callback, 8-database workspace setup
├── features_services/
│   ├── llm_conversation.py     # intent routing, dual-LLM calls, route_intent
│   ├── memory_journal.py       # all Neo4j reads and writes
│   ├── notion.py               # Notion CRUD, task/reminder save, mark done
│   ├── notion_agent.py         # autonomous Task Agent, /organise, progress bar
│   └── reminders.py            # reminder scheduler, Neo4j reminder queries
├── models/
│   ├── database.py             # SQLAlchemy table definitions (7 tables)
│   ├── db.py                   # all PostgreSQL CRUD functions
│   ├── db_hooks.py             # mirror hooks — called alongside Neo4j/Notion saves
│   └── db_helpers.py           # helper wrappers for OAuth and user management
alembic/                        # Alembic migration files
app.py                          # FastAPI entry point, scheduler startup
requirements.txt
.env.example
```

---

## Setup

```bash
git clone https://github.com/uroojkhan01/SecondBrain_CognitiveSystem.git
cd SecondBrain_CognitiveSystem
pip install -r requirements.txt
cp .env.example .env
# fill in your credentials
alembic upgrade head
uvicorn app:app --host 0.0.0.0 --port 8080
```

**Required environment variables:**

```
TELEGRAM_BOT_TOKEN
GROQ_API_KEY
GROQ_API_KEY_1
ANTHROPIC_API_KEY
NEO4J_URI
NEO4J_USERNAME
NEO4J_PASSWORD
NOTION_CLIENT_ID
NOTION_CLIENT_SECRET
NOTION_REDIRECT_URI
DATABASE_URL
ENABLE_LLM_API
```

---

## Connect to the database

Use TablePlus, DBeaver, or any PostgreSQL client:

| Field | Value |
|---|---|
| Host | `secondbrain-db-do-user-37649724-0.a.db.ondigitalocean.com` |
| Port | `25060` |
| User | `doadmin` |
| Database | `defaultdb` |
| SSL | Required |

Password shared privately by the team.

---

## Team

| Person | Role | Key contributions |
|---|---|---|
| Urooj Irfat | AI / Software Engineer | FastAPI backend, LLM integration (Groq + Claude fallback), Neo4j schema and memory service, intent routing, Telegram bot, voice transcription pipeline |
| Hamna Rashid Ahmed | AI / Software Engineer | Notion OAuth flow, 8-database workspace auto-setup, Task Agent, APScheduler (4 jobs), reminder scheduler, daily summary, progress bar sync |
| Niso Sharifzoda | Database Engineer | PostgreSQL schema design, SQLAlchemy models, Alembic migrations, db_hooks mirror layer, cross-store data consistency |
| Khurram Ameer Randhawa | Product / PM | Scope definition, user stories, milestone tracking, Notion workspace schema planning, reminder agent |

---

## Course

**Chat, Search and Summaries: Smarter Apps with LLMs**  
Instructor: Tim Landgraf  
Freie Universität Berlin  
Summer Semester 2026