# FinOps.AI

**An Enterprise-Grade, Multi-Agent Azure Cloud Intelligence Platform**

---

## Table of Contents

1. [Overview](#1-overview)
2. [Key Capabilities](#2-key-capabilities)
3. [System Architecture](#3-system-architecture)
4. [Core Components](#4-core-components)
5. [Technology Stack](#5-technology-stack)
6. [Repository Structure](#6-repository-structure)
7. [Getting Started](#7-getting-started)
8. [Deployment](#8-deployment)
9. [Roadmap](#9-roadmap)
10. [Author](#10-author)

---

## 1. Overview

FinOps.AI is a generative-AI-driven cloud operations platform that unifies financial management and operational oversight of Microsoft Azure environments. It integrates a multi-agent architecture, Azure cloud services, the Model Context Protocol (MCP), governance controls, predictive forecasting, anomaly detection, and approval workflows into a single operational intelligence system.

The platform enables organizations to:

- Monitor Azure infrastructure and resource health
- Analyze and attribute cloud spending
- Detect cost and behavioral anomalies
- Forecast future expenditure
- Enforce governance and compliance policies
- Automate cloud operations under controlled approval
- Manage approval workflows through Microsoft Teams
- Receive AI-generated optimization recommendations

---

## 2. Key Capabilities

| Capability | Description |
|---|---|
| Cost Intelligence | Azure cost analysis, budget monitoring, and optimization recommendations |
| Operational Visibility | Resource inventory, infrastructure monitoring, and health analysis |
| Governance & Compliance | Azure Policy integration with approval-gated execution |
| Predictive Analytics | XGBoost-based spend forecasting to support budget planning |
| Anomaly Detection | Isolation Forest-based detection of cost spikes and unusual resource behavior |
| Collaboration | Microsoft Teams integration with approval cards and proactive notifications |
| Secure Tool Orchestration | MCP layer providing governed, guardrailed tool execution |

---

## 3. System Architecture

FinOps.AI follows a layered architecture. User requests originate in the React frontend, pass through the FastAPI backend, and are routed by a LangGraph multi-agent orchestrator. Specialized agents perform their tasks, subject to governance review, and interact with Azure services exclusively through the MCP layer.

```text
React Frontend
       |
       v
FastAPI Backend
       |
       v
LangGraph Multi-Agent Orchestrator
       |
       +---------------------+
       |                     |
       v                     v
  FinOps Agent        CloudOps Agent
       |                     |
       +----------+----------+
                  |
                  v
          Governance Agent
                  |
                  v
             MCP Layer
                  |
                  v
   Azure Cost Management
   Azure Resource Graph
   Azure Monitor
   Azure Advisor
   Azure Policy
   Azure OpenAI
   Azure Container Apps
```

---

## 4. Core Components

### 4.1 FinOps Agent

Responsible for the financial analysis domain:

- Azure cost analysis
- Cost optimization recommendations
- Budget monitoring
- Resource utilization analysis

### 4.2 CloudOps Agent

Responsible for the operational domain:

- Resource inventory management
- Infrastructure monitoring
- Operational recommendations
- Resource health analysis

### 4.3 Governance Agent

Responsible for security, compliance, and control:

- Azure Policy integration
- Compliance monitoring
- Governance workflows
- Approval-based execution of actions

### 4.4 Forecasting Engine

- XGBoost-based time-series forecasting
- Future spend prediction
- Budget planning support

### 4.5 Anomaly Detection

- Isolation Forest-based anomaly detection
- Cost spike detection
- Resource behavior analysis

### 4.6 Microsoft Teams Integration

- Microsoft Teams Bot Framework integration
- Interactive approval cards
- Proactive notifications
- Chat-based cloud operations

### 4.7 MCP Layer

- Tool orchestration
- Secure execution
- Governance controls
- Enterprise guardrails

---

## 5. Technology Stack

| Layer | Technologies |
|---|---|
| Frontend | React, Vite, JavaScript |
| Backend | Python, FastAPI |
| AI & Agent Framework | Azure OpenAI, LangGraph, Multi-Agent Architecture |
| Cloud Platform | Microsoft Azure: Azure OpenAI, Container Apps, Monitor, Resource Graph, Cost Management APIs |
| Infrastructure | Docker, Terraform, Azure Container Registry |
| Machine Learning | XGBoost (forecasting), Isolation Forest (anomaly detection) |

---

## 6. Repository Structure

```text
finops-ai/
├── backend/     # FastAPI service, agents, MCP layer, ML models
├── frontend/    # React + Vite web application
├── terraform/   # Infrastructure-as-code for Azure resources
├── scripts/     # Build and deployment automation
└── docs/        # Project documentation
```

---

## 7. Getting Started

### 7.1 Prerequisites

- Python 3.x and a virtual environment manager
- Node.js and npm
- Docker
- Terraform
- An Azure subscription with access to the services listed in Section 5
- Appropriate Azure credentials and Azure OpenAI configuration

### 7.2 Local Development

**Backend**

```bash
cd backend
uvicorn main:app --reload
```

**Frontend**

```bash
cd frontend
npm run dev
```

---

## 8. Deployment

### 8.1 Azure Deployment

Container images are built and pushed to Azure Container Registry, after which infrastructure changes are applied via Terraform:

```powershell
.\scripts\deploy-images.ps1 -ApplyAfterPush
```

---

## 9. Roadmap

Planned enhancements include:

- Slack integration
- Kubernetes remediation
- Advanced Security Agent
- Automated blob recovery
- Twilio voice alerting
- Autonomous cloud optimization

---

## 10. Author

**Madhubala A**
Integrated M.Tech, Data Science
Vellore Institute of Technology (VIT), Vellore
