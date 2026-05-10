<div align="center">

# 🏫 AISTU - 校园 AI 教务助手平台

**Smart Campus Educational Administration Platform with AI-Powered Student Care**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://python.org)
[![Vue](https://img.shields.io/badge/Vue-3.4-brightgreen.svg)](https://vuejs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135-teal.svg)](https://fastapi.tiangolo.com)

[English](#overview) · [功能特性](#-功能特性) · [快速开始](#-快速开始) · [架构设计](#-架构设计) · [文档](#-文档)

</div>

---

## Overview

AISTU is an intelligent campus platform for K-12 schools, combining traditional educational administration with AI-powered student care analytics. It goes beyond simple risk scoring — it builds an **explainable, reviewable, and continuously improvable** student care inference system.

The platform integrates structured campus data, rule-based inference, Bayesian probability correction, and multi-agent analysis into a unified workflow, enabling teachers to manage daily administration tasks and receive intelligent student care insights in one place.

## ✨ 功能特性

### 📋 基础教务管理
- Student, teacher, class, and score management
- Tag system with review and approval workflow
- Excel import/export with template support

### 🧠 学生关怀研判 (Core Highlight)
- **Six-Dimension Risk Profile**: Emotion, social, safety, family, academic, behavior
- **Multi-Agent Inference**: Expert agents analyze each dimension, then synthesize conclusions
- **Bayesian Correction**: Dynamic priors and likelihood ratios for evidence accumulation
- **Social Isolation Detection**: Dedicated analysis module beyond general risk scoring
- **Graph-Enhanced Insights**: Neo4j relationship network reveals hidden social and safety signals
- **Teacher Review Loop**: Confirm real risks, mark false positives, write-back resolutions

### 📚 校规知识服务
- School rule entry, vector search, and AI-powered Q&A
- Rule citation in student care inference

### 🤖 AI 教务工具
- Comment generation, score diagnosis, notice polishing, meeting planning
- Interview preparation, discipline analysis, group assignment

### 🎯 智能分组分班
- Balanced class assignment based on student profiles
- Teacher grouping optimization

## 🚀 快速开始

### Prerequisites

| Service | Version | Purpose |
|---------|---------|---------|
| Python | 3.11+ | Backend runtime |
| Node.js | 18+ | Frontend runtime |
| MySQL | 8.0+ | Primary data store |
| Milvus | 2.x | Vector search for school rules |
| Neo4j | 5.x | Graph relationship analysis |

### One-Click Start

```bash
# Clone the repository
git clone https://github.com/zfu691531-hash/aistu.git
cd aistu

# Start both frontend and backend
python main.py
```

### Backend Setup

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your database and AI service credentials

# Initialize database
mysql -u root -p < ../docs/init_database.sql

# Start the server
python main.py
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Configure API endpoint (edit src/api/config.js if needed)

# Start dev server
npm run dev

# Or build for production
npm run build
```

### Demo Accounts

| Username | Password | Role |
|----------|----------|------|
| admin | admin123 | Administrator |
| wang_math | teacher123 | Teacher |
| stu_2024001 | student123 | Student |

## 🏗️ 架构设计

### Platform Architecture

```
Frontend (Vue 3 + Element Plus)
  → Backend API (FastAPI)
    → Business Services
      → MySQL / SQLAlchemy        (Primary data)
      → Milvus                     (Vector search)
      → Neo4j                      (Graph analysis)
      → LangChain / LangGraph      (Agent orchestration)
```

### Student Care Inference Pipeline

```
Data Input → Signal Extraction → Rule Scoring → Bayesian Correction → Multi-Agent Analysis → Teacher Review
```

<div align="center">
  <img src="docs/assets/care-architecture.png" alt="Student Care Architecture" width="600">
</div>

**Why this architecture works:**

| Layer | Role | Guarantee |
|-------|------|-----------|
| Rule Layer | Stable, explainable base scoring | Even without LLM, produces reliable profiles |
| Bayesian Layer | Probability correction with evidence | Handles multi-evidence accumulation and correlation |
| Agent Layer | Dimension-specific expert analysis | Translates complex signals into teacher-friendly insights |
| Feedback Layer | Continuous improvement loop | Teacher reviews refine future assessments |

## 📁 项目结构

```
aistu/
├── backend/
│   ├── api/                  # FastAPI route handlers
│   ├── services/             # Core business logic
│   │   ├── student_care_*.py # Student care inference pipeline
│   │   ├── ai/               # AI tool services
│   │   └── ...               # CRUD & export services
│   ├── schemas/              # Request/response models
│   ├── core/                 # Config, constants, auth
│   ├── database/models/      # SQLAlchemy ORM models
│   ├── scripts/              # Init & demo data scripts
│   └── tests/                # Test suite
├── frontend/
│   ├── src/views/            # Page-level views
│   ├── src/components/       # Shared & business components
│   ├── src/stores/           # Pinia state management
│   ├── src/router/           # Vue Router config
│   ├── src/api/              # API client modules
│   └── src/utils/            # Utility functions
├── docs/                     # Documentation & assets
└── main.py                   # One-click launcher
```

## 🔑 Key Implementation Files

The student care inference pipeline:

| File | Responsibility |
|------|---------------|
| `backend/services/student_care_service.py` | Profile construction, base scoring, refresh |
| `backend/services/student_care_agent_service.py` | Multi-agent inference, synthesis, review stats |
| `backend/services/student_care_bayes_service.py` | Bayesian correction & evidence processing |
| `backend/services/student_care_isolation_service.py` | Social isolation专项 analysis |
| `backend/services/student_care_graph_service.py` | Neo4j graph signal generation |
| `backend/services/assistant_service.py` | AI summary, risk text extraction |
| `backend/api/student_care.py` | Student care API endpoints |

## 🛠️ 技术栈

| Category | Technology |
|----------|-----------|
| **Backend Framework** | FastAPI + Uvicorn |
| **ORM** | SQLAlchemy + Alembic |
| **Database** | MySQL 8.0 |
| **AI Orchestration** | LangChain + LangGraph |
| **Vector Search** | Milvus |
| **Graph Database** | Neo4j |
| **Frontend Framework** | Vue 3 + Vite |
| **UI Library** | Element Plus |
| **State Management** | Pinia |
| **HTTP Client** | Axios |

## 📖 文档

| Document | Description |
|----------|-------------|
| [学生关怀智能研判体系设计](docs/学生关怀智能研判体系设计.md) | Business loop, layered design, implementation scope |
| [学生关怀关键技术亮点说明](docs/学生关怀关键技术亮点说明.md) | Technical highlights for presentation & review |
| [学生关怀多智能体风险研判方案](docs/学生关怀多智能体风险研判方案.md) | Multi-agent risk inference methodology |
| [项目技术架构总览](docs/项目技术架构总览.md) | Full architecture overview |
| [数据库初始化SQL](docs/init_database.sql) | Database DDL (v1.1.0) |
| [演示账号与案例说明](docs/演示账号与案例说明-2026-04-10.md) | Demo accounts & walkthrough |

## ⚠️ Disclaimer

- Student care and risk identification capabilities are designed as **decision-support tools for teachers**, not replacements for professional judgment.
- Inference results should be used in conjunction with real campus observations, records, and home-school communication.
- For public demonstrations, use provided demo data and case documentation.

## 📄 License

This project is licensed under the [MIT License](LICENSE).

---

<div align="center">

**If this project helps you, please consider giving it a ⭐!**

</div>
