# 🧠 Second Brain

A Telegram-based AI assistant built to help people with ADHD manage tasks, reminders, and memory without the friction of traditional productivity tools.

**Status:** ✅ Live  
**Bot:** [@secondbrain01_bot](https://t.me/secondbrain01_bot)  
**Repo:** [github.com/uroojkhan01/SecondBrain_CognitiveSystem](https://github.com/uroojkhan01/SecondBrain_CognitiveSystem)

---

## What it does

You talk to it on Telegram — by text or voice — and it handles the rest. It saves your tasks, sets reminders, remembers things you tell it, and organises everything into your Notion workspace automatically. No manual sorting, no switching between apps.

Built specifically for people with ADHD, where the hardest part is often just capturing a thought before it disappears.

---

## The problem it solves

- You have a thought while walking — send a voice note, done
- You need a reminder — just say it naturally, it figures out the time
- You dump 5 tasks at once — it extracts each one individually
- It remembers your doctor's name, your sister's birthday, your coworker's allergy — and uses that context in future conversations
- Every evening at 10pm it sends you a summary of your day

---

## How it works

```
You (Telegram)
      ↓
FastAPI receives the message
      ↓
LLM classifies intent (Groq first, Claude if Groq fails)
      ↓
Saves to Neo4j + PostgreSQL + Notion
      ↓
Background jobs run every 5–30 min (reminders, task organiser, daily summary)
```

---

## Tech stack

| What | How |
|---|---|
| Backend | FastAPI (Python 3.11) |
| Deployment | DigitalOcean App Platform |
| Primary LLM | Groq — LLaMA 3.3-70b |
| Fallback LLM | Claude Haiku / Sonnet (auto-switches when Groq hits limits) |
| Voice transcription | faster-whisper (local, runs on server) |
| Long-term memory | Neo4j AuraDB (knowledge graph) |
| Structured data | PostgreSQL on DigitalOcean |
| ORM / migrations | SQLAlchemy + Alembic |
| User workspace | Notion (OAuth 2.0) |
| Background jobs | APScheduler |
| Interface | Telegram Bot API |

---

## What the LLM can do

15+ intents supported:

`create_task` `set_reminder` `save_memory` `mark_done` `mark_undone` `update_task` `update_reminder` `delete_task` `delete_reminder` `update_project` `update_memory` `brain_dump` `habit_track` `seek_advice` `conversation`

The LLM receives the user's full conversation history (last 20 turns) plus their Neo4j context — recent memories, tasks, entities, reminders — on every message. This is what makes it feel like it actually remembers you.

---

## Data layer

Three stores, all kept in sync:

**PostgreSQL** — raw structured data, source of truth

| Table | What's in it |
|---|---|
| users | chat_id, name, Notion token |
| messages | every message, input type, intent |
| tasks | title, due date, status, Notion page ID, Neo4j node ID |
| reminders | text, remind_at, is_sent |
| voice_messages | file ID, transcription |
| notion_databases | linked Notion DB IDs per user |

**Neo4j** — knowledge graph for memory and relationships

```
(User) -[:REMEMBERS]→ (Memory)
(User) -[:KNOWS]→ (Entity) -[:ASSOCIATED_WITH]→ (Memory)
(User) -[:CREATED]→ (Task)
(User) -[:SET]→ (Reminder)
```

**Notion** — 8 databases auto-created on first login

- Tasks & To Dos
- Master Projects DB (with progress bar)
- Health & Fitness
- Finance & Wealth
- Career & Professional
- Personal Growth & Learning
- Home & Lifestyle
- Family & Friends

---

## Background jobs

Four jobs run on a schedule, no user action needed:

| Job | When | What it does |
|---|---|---|
| Reminder check | Every 5 min | Finds due reminders, sends Telegram alert, marks as sent |
| Task organiser | Every 30 min | LLM reads new tasks, categorises into life areas, links to projects |
| Progress sync | Every 10 min | Updates project progress bar based on completed tasks |
| Daily summary | 22:00 Berlin | Sends personalised daily digest to every user |

---

## Project structure

```
assistant_backend_1/
├── api/handlers/
│   ├── telegram_handler.py     # incoming messages, hook calls
│   └── notion_handler.py       # OAuth, workspace setup
├── features_services/
│   ├── llm_conversation.py     # intent routing, LLM calls
│   ├── memory_journal.py       # Neo4j reads/writes
│   ├── notion.py               # Notion CRUD
│   ├── notion_agent.py         # autonomous task organiser agent
│   └── reminders.py            # reminder scheduler
├── models/
│   ├── database.py             # SQLAlchemy table definitions (7 tables)
│   ├── db.py                   # all CRUD functions
│   ├── db_hooks.py             # mirror hooks into Postgres
│   └── db_helpers.py           # helper wrappers
alembic/                        # migration files
app.py                          # FastAPI entry point
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

**Required env vars:**

```
TELEGRAM_BOT_TOKEN
GROQ_API_KEY
ANTHROPIC_API_KEY
NEO4J_URI
NEO4J_USERNAME
NEO4J_PASSWORD
NOTION_CLIENT_ID
NOTION_CLIENT_SECRET
NOTION_REDIRECT_URI
DATABASE_URL
```

---

## Connect to the database

Use TablePlus, DBeaver, or any Postgres client:

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

| Person | Role | What they built |
|---|---|---|
| Urooj Irfat | AI / Software Engineer | FastAPI backend, LLM integration, Neo4j, intent routing, Telegram bot, voice transcription |
| Hamna Rashid Ahmed | AI / Software Engineer | Notion OAuth, workspace auto-setup, Task Agent, APScheduler, reminder scheduler, daily summary |
| Niso Sharifzoda | Database Engineer | PostgreSQL schema, SQLAlchemy models, Alembic migrations, Postgres hooks |
| Khurram Ameer Randhawa | Product / PM | Scope, user stories, milestone tracking, Notion schema planning |

---

## Course

Large Language Models — Final Project  
Instructor: Tim Landgraf  
Freie Universität Berlin
