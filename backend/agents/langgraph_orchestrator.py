"""
agents/langgraph_orchestrator.py
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
LangGraph-based multi-agent orchestration for FinOps AI Platform.

Architecture:
  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
  â”‚           Supervisor Agent         â”‚  â† routes queries to specialists
  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
               â”‚
       â”Œâ”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
       â–¼       â–¼        â–¼          â–¼          â–¼
   FinOps  CloudOps  Anomaly  Forecast  Approvals
   Agent    Agent    Agent    Agent     Agent

Each agent:
  â€¢ Has a GPT-4o system prompt scoped to its domain
  â€¢ Gets access to specific MCP tools
  â€¢ Can propose actions (held in approval queue)
  â€¢ Returns structured {response, actions, tool_calls}

Requires:
  pip install langgraph langchain langchain-openai openai
"""

from __future__ import annotations

import json
import logging
import traceback
from typing import Any, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langgraph.graph import END, StateGraph

from mcp_layer.tools import agent_tools_schema, execute_tool

try:
    from config import settings
except ImportError:
    class _Settings:
        AZURE_OPENAI_ENDPOINT = ""
        AZURE_OPENAI_KEY = ""
        AZURE_OPENAI_DEPLOYMENT = "gpt-4o"
        AZURE_OPENAI_API_VERSION = "2024-02-15-preview"
    settings = _Settings()

logger = logging.getLogger("finops.agents")


# â”€â”€â”€ State â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class AgentState(TypedDict):
    messages: list
    current_agent: str
    agent_plan: list[str]
    tool_results: list[dict]
    final_response: str
    actions_proposed: list[dict]
    error: str | None


# â”€â”€â”€ LLM factory â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _make_llm(tools_schema: list[dict] | None = None):
    config_issue = settings.azure_openai_configuration_issue()
    if config_issue:
        raise RuntimeError(config_issue)
    if settings.openai_endpoint_family() == "azure_foundry":
        llm = ChatOpenAI(
            api_key=settings.AZURE_OPENAI_KEY,
            base_url=settings.openai_v1_base_url(),
            model=settings.AZURE_OPENAI_DEPLOYMENT,
            temperature=0.1,
            max_tokens=1500,
        )
    else:
        llm = AzureChatOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_KEY,
            azure_deployment=settings.AZURE_OPENAI_DEPLOYMENT,   # "gpt-4o"
            api_version=settings.AZURE_OPENAI_API_VERSION,
            temperature=0.1,
            max_tokens=1500,
        )
    if tools_schema:
        return llm.bind_tools(tools_schema)
    return llm


# â”€â”€â”€ Agent prompts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

SUPERVISOR_PROMPT = """
You are the FinOps AI Platform supervisor. Your job is to route user queries
to the specialist agent or agents needed to answer the request. Use multiple
agents when the user asks for combined analysis, such as cost + resources,
forecast + anomalies, security + approvals, or operations + cost impact.

Available agents:
- finops_agent:    Azure cost analysis, budget tracking, spend optimisation
- cloudops_agent:  Azure resource health, infrastructure inventory, Advisor recs
- security_agent:  Azure Defender, security posture, policy compliance
- anomaly_agent:   Cost anomaly detection, unusual spend patterns
- forecast_agent:  Cost forecasting, trend prediction, budget projection
- approval_agent:  Pending approvals, action proposals, remediation queue

Respond ONLY with JSON:
{"routes": ["<agent_name>", "..."], "reason": "<short reason>"}

Use at most 4 agents. Never include an agent that is not needed.
"""

FINOPS_PROMPT = """
You are a senior Azure FinOps specialist AI. You have access to real Azure 
Cost Management data via tools.

Your responsibilities:
- Analyse month-to-date spend and trends
- Identify overspend and budget risks  
- Provide actionable cost optimisation recommendations
- Explain cost drivers clearly with numbers
- Propose actions (with estimated savings) for human approval

Always:
- Use the tools to get REAL data before answering
- Quantify savings in USD
- Be specific about resources and services
- If billing data isn't available yet, explain why (new subscription)

Tone: Professional, data-driven, concise.
"""

CLOUDOPS_PROMPT = """
You are a senior Azure CloudOps engineer AI. You monitor infrastructure health
and resource optimisation via tools.

Your responsibilities:
- Inventory and health status of all Azure resources
- Surface Azure Advisor recommendations
- Identify underutilised or orphaned resources
- Propose right-sizing and cleanup actions for approval
- Detect configuration drift and security gaps

Always use tools to get live Azure data before responding.
Propose specific actions with justifications and estimated savings.
"""

SECURITY_PROMPT = """
You are a senior Azure security and governance specialist AI.

Your responsibilities:
- Inspect Defender for Cloud and Resource Graph security findings
- Review Azure Policy compliance state
- Explain security posture without inventing findings
- Recommend least-privilege and policy remediation steps
- Propose risky changes only through the approval workflow

Always use live tools first. If Defender, Policy Insights, or RBAC permissions
are not configured, say exactly which capability is missing.
"""

ANOMALY_PROMPT = """
You are an Azure cost and performance anomaly detection specialist.

Your responsibilities:
- Identify unusual cost spikes or drops
- Detect unexpected resource usage patterns
- Correlate anomalies with infrastructure changes
- Classify severity (critical / warning / info)
- Recommend investigation steps

Use the anomaly detection tools to get current detections.
Explain anomalies clearly with root-cause hypotheses.
"""

FORECAST_PROMPT = """
You are an Azure cloud cost forecasting specialist.

Your responsibilities:
- Generate 30/60/90-day cost forecasts
- Identify cost trend inflection points
- Project budget burn-rate and depletion dates
- Model "what-if" scenarios for infrastructure changes
- Provide confidence intervals for forecasts

Use the forecast tools to get ML-based predictions.
Present forecasts with clear assumptions and confidence levels.
"""

APPROVAL_PROMPT = """
You are the FinOps AI approval workflow manager.

Your responsibilities:
- List and summarise pending approval requests
- Explain proposed actions clearly
- Assess risk level of each action
- Highlight estimated savings and impact
- Flag urgent or time-sensitive approvals

Use tools to get the current approval queue.
Present each pending item with: action, resource, justification, savings, risk.
"""


# â”€â”€â”€ Agent tool assignments â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

AGENT_TOOLS = {
    "finops_agent":   ["get_cost_summary", "get_cost_by_service", "get_budget_status", "propose_action"],
    "cloudops_agent": ["list_resources", "get_advisor_recommendations", "get_resource_health", "propose_action"],
    "security_agent": ["get_security_posture", "get_policy_compliance", "propose_action"],
    "anomaly_agent":  ["get_anomalies", "get_cost_summary", "get_cost_by_service"],
    "forecast_agent": ["get_cost_forecast", "get_cost_summary"],
    "approval_agent": ["list_pending_approvals"],
}

AGENT_PROMPTS = {
    "finops_agent":   FINOPS_PROMPT,
    "cloudops_agent": CLOUDOPS_PROMPT,
    "security_agent": SECURITY_PROMPT,
    "anomaly_agent":  ANOMALY_PROMPT,
    "forecast_agent": FORECAST_PROMPT,
    "approval_agent": APPROVAL_PROMPT,
}


# â”€â”€â”€ Node functions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def supervisor_node(state: AgentState) -> AgentState:
    """Routes the query to the right specialist agent or agents."""
    user_msg = state["messages"][-1]["content"] if state["messages"] else ""
    routes = await _plan_agents(user_msg)
    logger.info("Supervisor routed to: %s", ",".join(routes))
    return {**state, "current_agent": routes[0], "agent_plan": routes}


def _normalise_routes(raw_routes: Any) -> list[str]:
    if isinstance(raw_routes, str):
        raw_routes = [raw_routes]
    routes: list[str] = []
    for item in raw_routes or []:
        agent = str(item).strip()
        if agent in AGENT_TOOLS and agent not in routes:
            routes.append(agent)
    return routes[:4] or ["finops_agent"]


def _keyword_agent_plan(message: str) -> list[str]:
    msg = message.lower()
    signals = [
        ("finops_agent", ["cost", "spend", "budget", "saving", "service", "resource cost", "component"]),
        ("cloudops_agent", ["resource", "vm", "blob", "storage", "app service", "container app", "health", "advisor", "scale", "restart", "stop", "start", "delete", "create"]),
        ("security_agent", ["security", "defender", "policy", "compliance", "rbac", "permission"]),
        ("anomaly_agent", ["anomaly", "spike", "unusual", "outlier"]),
        ("forecast_agent", ["forecast", "predict", "projection", "trend"]),
        ("approval_agent", ["approval", "approve", "reject", "pending"]),
    ]
    routes = [agent for agent, words in signals if any(word in msg for word in words)]
    return routes[:4] or ["finops_agent"]


async def _plan_agents(user_msg: str) -> list[str]:
    llm = _make_llm()
    messages = [
        SystemMessage(content=SUPERVISOR_PROMPT),
        HumanMessage(content=user_msg),
    ]
    try:
        response = await llm.ainvoke(messages)
        text = response.content.strip()
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        routing = json.loads(text)
        return _normalise_routes(routing.get("routes") or routing.get("route"))
    except Exception as exc:
        logger.warning("Supervisor routing failed: %s: %s; using keyword multi-agent fallback", type(exc).__name__, exc)
        logger.error("Supervisor routing traceback:\n%s", traceback.format_exc())
        return _keyword_agent_plan(user_msg)


async def _run_agent_with_tools(
    agent_name: str,
    user_message: str,
    history: list[dict],
) -> dict:
    """
    Runs a specialist agent with tool-use loop:
    1. Send user message + history to LLM
    2. If LLM wants to call tools â†’ execute them
    3. Feed results back â†’ get final answer
    Max 3 tool-call rounds to avoid infinite loops.
    """
    tools_schema = agent_tools_schema(AGENT_TOOLS.get(agent_name, []))
    llm          = _make_llm(tools_schema if tools_schema else None)
    system_msg   = AGENT_PROMPTS.get(agent_name, FINOPS_PROMPT)

    messages = [SystemMessage(content=system_msg)]
    for h in history[-6:]:           # last 3 turns of context
        role = h.get("role", "user")
        if role == "user":
            messages.append(HumanMessage(content=h["content"]))
        elif role == "assistant":
            messages.append(AIMessage(content=h["content"]))

    messages.append(HumanMessage(content=user_message))

    tool_results: list[dict] = []
    actions_proposed: list[dict] = []

    for _round in range(3):   # max 3 tool-call rounds
        response = await llm.ainvoke(messages)

        # Check for tool calls
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            # Final text answer
            return {
                "response": response.content,
                "tool_results": tool_results,
                "actions_proposed": actions_proposed,
            }

        # Execute each tool call
        messages.append(response)   # AI message with tool_calls
        for tc in tool_calls:
            tool_name = tc["name"]
            arguments = tc.get("args", {})
            logger.info("Agent %s calling tool: %s(%s)", agent_name, tool_name, arguments)

            result = await execute_tool(tool_name, arguments)
            tool_results.append({"tool": tool_name, "result": result})

            # Track proposed actions
            if tool_name == "propose_action":
                actions_proposed.append(result)

            messages.append(
                ToolMessage(
                    content=json.dumps(result, default=str),
                    tool_call_id=tc.get("id", tool_name),
                )
            )

    # If we exhausted rounds, force a final response
    final = await llm.ainvoke(messages)
    return {
        "response": final.content,
        "tool_results": tool_results,
        "actions_proposed": actions_proposed,
    }


async def specialist_node(state: AgentState) -> AgentState:
    """Runs the routed specialist agent."""
    agent_name  = state.get("current_agent", "finops_agent")
    user_msg    = state["messages"][-1]["content"] if state["messages"] else ""
    history     = state["messages"][:-1]

    try:
        result = await _run_agent_with_tools(agent_name, user_msg, history)
        return {
            **state,
            "final_response":    result["response"],
            "tool_results":      state.get("tool_results", []) + result["tool_results"],
            "actions_proposed":  state.get("actions_proposed", []) + result["actions_proposed"],
            "error":             None,
        }
    except Exception as exc:
        logger.error("Specialist node %s failed: %s: %s", agent_name, type(exc).__name__, exc)
        logger.error("Specialist node traceback:\n%s", traceback.format_exc())
        return {
            **state,
            "final_response": (
                f"I encountered an error while processing your request via the "
                f"{agent_name.replace('_', ' ').title()}. "
                f"Error: {type(exc).__name__}: {exc}"
            ),
            "error": str(exc),
        }


def route_after_supervisor(state: AgentState) -> Literal[
    "finops_agent", "cloudops_agent", "security_agent", "anomaly_agent",
    "forecast_agent", "approval_agent",
]:
    """Edge function: supervisor â†’ which specialist node."""
    return state.get("current_agent", "finops_agent")


# â”€â”€â”€ Graph builder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # Nodes
    graph.add_node("supervisor",     supervisor_node)
    graph.add_node("finops_agent",   specialist_node)
    graph.add_node("cloudops_agent", specialist_node)
    graph.add_node("security_agent", specialist_node)
    graph.add_node("anomaly_agent",  specialist_node)
    graph.add_node("forecast_agent", specialist_node)
    graph.add_node("approval_agent", specialist_node)

    # Edges
    graph.set_entry_point("supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "finops_agent":   "finops_agent",
            "cloudops_agent": "cloudops_agent",
            "security_agent": "security_agent",
            "anomaly_agent":  "anomaly_agent",
            "forecast_agent": "forecast_agent",
            "approval_agent": "approval_agent",
        },
    )
    for agent in AGENT_TOOLS:
        graph.add_edge(agent, END)

    return graph.compile()


# â”€â”€â”€ Public entry point â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_COMPILED_GRAPH = None


def _get_graph():
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is None:
        _COMPILED_GRAPH = build_graph()
    return _COMPILED_GRAPH


async def run_agent(
    message: str,
    history: list[dict] | None = None,
    agent_override: str | None = None,
) -> dict:
    """
    Main entry point for the LangGraph multi-agent system.

    Args:
        message:        User's natural language query
        history:        Previous messages [{role, content}, ...]
        agent_override: Force a specific agent (skip supervisor routing)

    Returns:
        {
          "response":         str,
          "agent_used":       str,
          "tool_results":     list,
          "actions_proposed": list,
          "error":            str | None
        }
    """
    history = history or []
    initial_state: AgentState = {
        "messages":        history + [{"role": "user", "content": message}],
        "current_agent":   agent_override or "finops_agent",
        "agent_plan":      [agent_override] if agent_override else [],
        "tool_results":    [],
        "final_response":  "",
        "actions_proposed": [],
        "error":           None,
    }

    # If override is set, skip supervisor
    if agent_override:
        result = await specialist_node(initial_state)
    else:
        try:
            planned_agents = await _plan_agents(message)
            if len(planned_agents) > 1:
                result = await _run_multi_agent_plan(initial_state, planned_agents)
            else:
                initial_state["current_agent"] = planned_agents[0]
                initial_state["agent_plan"] = planned_agents
                result = await specialist_node(initial_state)
        except Exception as exc:
            logger.error("LangGraph invocation failed: %s: %s", type(exc).__name__, exc)
            logger.error("LangGraph traceback:\n%s", traceback.format_exc())
            # Fallback: run directly without graph
            fallback_plan = _keyword_agent_plan(message)
            initial_state["current_agent"] = fallback_plan[0]
            initial_state["agent_plan"] = fallback_plan
            result = await specialist_node(initial_state)

    return {
        "response":         result.get("final_response", "No response generated."),
        "agent_used":       ", ".join(result.get("agent_plan") or [result.get("current_agent", "unknown")]),
        "tool_results":     result.get("tool_results", []),
        "actions_proposed": result.get("actions_proposed", []),
        "error":            result.get("error"),
    }


async def _run_multi_agent_plan(initial_state: AgentState, planned_agents: list[str]) -> AgentState:
    responses: list[str] = []
    tool_results: list[dict] = []
    actions: list[dict] = []
    errors: list[str] = []

    for agent in planned_agents:
        state: AgentState = {**initial_state, "current_agent": agent, "agent_plan": planned_agents}
        result = await specialist_node(state)
        heading = agent.replace("_", " ").title()
        responses.append(f"### {heading}\n{result.get('final_response', '')}")
        tool_results.extend(result.get("tool_results", []))
        actions.extend(result.get("actions_proposed", []))
        if result.get("error"):
            errors.append(f"{agent}: {result['error']}")

    return {
        **initial_state,
        "current_agent": planned_agents[0],
        "agent_plan": planned_agents,
        "final_response": "\n\n".join(responses),
        "tool_results": tool_results,
        "actions_proposed": actions,
        "error": "; ".join(errors) if errors else None,
    }

