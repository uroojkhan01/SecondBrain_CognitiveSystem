# 🧠 AI Memory Assistant

A memory-support assistant designed for people with ADHD, dementia, and Alzheimer’s.
The system helps users capture daily events, organize memories, and retrieve information through natural conversation.

---

# 🚀 Project Overview

The application uses:

* Telegram for conversational interaction
* Notion for structured memory storage
* OpenAI models for understanding and reasoning
* MCP backend server for orchestration and workflow management

Users can:

* log memories and events
* ask recall-based questions
* retrieve summaries and past activities
* organize information through natural language

Input can come from:

* Telegram conversations
* Notion entries and updates

---

# 🏗️ System Architecture

```text
Telegram / Notion
        ↓
      MCP Server
        ↓
    AI / LLM Layer
        ↓
   Memory Processing
        ↓
      Notion DB
```

---

# 📂 Project Structure

```text
backend/
├── api/
├── services/
├── models/
├── prompts/
├── utils/

tests/
docs/
```

---

# ⚙️ Core Components

## Telegram Integration

Handles:

* user conversations
* commands and responses
* message delivery

---

## MCP Backend

Acts as the central orchestrator:

* routes requests
* coordinates AI processing
* manages memory workflows

---

## AI / LLM Layer

Responsible for:

* intent detection
* memory structuring
* contextual responses
* reasoning over stored information

---

## Notion Integration

Responsible for:

* storing structured memories
* retrieving past information
* maintaining organized records

---

# 🧪 Development Workflow

# Branch structure:

```text
main       → stable production code
develop    → active integration branch
feature/*  → isolated feature development
```

# Workflow:

```text
feature branch
    ↓
develop
    ↓
main
```

---

# 🎯 MVP Goals

* Telegram-based interaction
* Memory logging
* Daily recall queries
* Notion memory storage
* AI-assisted responses

---

# ⚠️ Engineering Principles

* Keep architecture modular
* Separate business logic from APIs
* Prioritize reliability over complexity
* Keep responses simple and clear
* Build testability from the start

---

# 👥 Team Responsibilities

# Project Manager

Responsible for:

feature planning
task coordination
timeline management
user experience validation
documentation and progress tracking

# AI / Backend Engineers

Responsible for:

Telegram bot integration
webhook handling
MCP server setup
API routing
backend infrastructure
AI/LLM integration
prompt engineering
intent classification
response generation
orchestration logic

# Database / Storage Engineer

Responsible for:

Notion database structure
memory schemas
data organization
retrieval workflows
storage consistency

# 📌 Current Status

Project initialization and architecture setup phase.
