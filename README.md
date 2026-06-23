\# FinOps.AI



Enterprise-Grade Multi-Agent Azure Cloud Intelligence Platform



\## Overview



FinOps.AI is a GenAI-powered cloud operations platform that combines Multi-Agent AI, Azure Cloud Services, MCP (Model Context Protocol), Governance Controls, Forecasting, Anomaly Detection, and Approval Workflows into a unified operational intelligence system.



The platform enables organizations to:



\- Monitor Azure infrastructure

\- Analyze cloud spending

\- Detect anomalies

\- Forecast future costs

\- Enforce governance policies

\- Automate cloud operations

\- Manage approval workflows

\- Integrate with Microsoft Teams

\- Generate AI-powered recommendations



\---



\## Architecture



```text

React Frontend

&#x20;       |

&#x20;       v

FastAPI Backend

&#x20;       |

&#x20;       v

LangGraph Multi-Agent Orchestrator

&#x20;       |

&#x20;       +---------------------+

&#x20;       |                     |

&#x20;       v                     v

&#x20;  FinOps Agent        CloudOps Agent

&#x20;       |                     |

&#x20;       +----------+----------+

&#x20;                  |

&#x20;                  v

&#x20;           Governance Agent

&#x20;                  |

&#x20;                  v

&#x20;             MCP Layer

&#x20;                  |

&#x20;                  v

Azure Cost Management

Azure Resource Graph

Azure Monitor

Azure Advisor

Azure Policy

Azure OpenAI

Azure Container Apps

```



\---



\## Core Features



\### FinOps Agent



\- Azure cost analysis

\- Cost optimization recommendations

\- Budget monitoring

\- Resource utilization analysis



\### CloudOps Agent



\- Resource inventory

\- Infrastructure monitoring

\- Operational recommendations

\- Resource health analysis



\### Security \& Governance



\- Azure Policy integration

\- Compliance monitoring

\- Governance workflows

\- Approval-based execution



\### Forecasting Engine



\- XGBoost-based forecasting

\- Future spend prediction

\- Budget planning support



\### Anomaly Detection



\- Isolation Forest anomaly detection

\- Cost spike detection

\- Resource behavior analysis



\### Teams Integration



\- Microsoft Teams Bot Framework integration

\- Approval cards

\- Proactive notifications

\- Chat-based cloud operations



\### MCP Layer



\- Tool orchestration

\- Secure execution

\- Governance controls

\- Enterprise guardrails



\---



\## Technology Stack



\### Frontend



\- React

\- Vite

\- JavaScript



\### Backend



\- FastAPI

\- Python



\### AI \& Agent Framework



\- Azure OpenAI

\- LangGraph

\- Multi-Agent Architecture



\### Cloud Platform



\- Microsoft Azure

\- Azure OpenAI

\- Azure Container Apps

\- Azure Monitor

\- Azure Resource Graph

\- Azure Cost Management APIs



\### Infrastructure



\- Docker

\- Terraform

\- Azure Container Registry



\### ML Models



\- XGBoost Forecasting

\- Isolation Forest Anomaly Detection



\---



\## Project Structure



```text

backend/

frontend/

terraform/

scripts/

docs/

```



\---



\## Deployment



\### Local



```bash

uvicorn main:app --reload

npm run dev

```



\### Azure



```powershell

.\\scripts\\deploy-images.ps1 -ApplyAfterPush

```



\---



\## Future Enhancements



\- Slack Integration

\- Kubernetes Remediation

\- Advanced Security Agent

\- Automated Blob Recovery

\- Twilio Voice Alerting

\- Autonomous Cloud Optimization



\---



\## Author



Madhubala A



VIT Vellore



Integrated M.Tech Data Science

