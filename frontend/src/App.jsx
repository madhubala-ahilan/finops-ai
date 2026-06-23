import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  ClipboardCheck,
  CheckSquare,
  CheckCircle2,
  Cloud,
  Container,
  DollarSign,
  ExternalLink,
  IndianRupee,
  KeyRound,
  Loader2,
  MessageSquare,
  Moon,
  PlayCircle,
  RefreshCw,
  Search,
  Send,
  Server,
  Settings,
  ShieldCheck,
  Sun,
  TerminalSquare,
  TrendingUp,
  WifiOff,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Brush,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import "./App.css";
import heroImage from "./assets/hero.png";

const API = window.__FINOPS_CONFIG__?.API_BASE_URL || import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const BUILD_VERSION = window.__FINOPS_CONFIG__?.BUILD_VERSION || import.meta.env.VITE_FINOPS_BUILD_VERSION || "local";
const STORAGE_KEY = "finops.azure.connection";
const THEME_KEY = "finops.ui.theme";
const CHART_COLORS = ["#2563eb", "#14b8a6", "#f97316", "#7c3aed", "#e11d48", "#0f766e", "#ca8a04", "#0891b2"];
const THEMES = [
  ["light", "Clean Light"],
  ["dark", "Midnight"],
  ["ocean", "Ocean"],
  ["forest", "Forest"],
  ["sunset", "Sunset"],
  ["royal", "Royal"],
  ["rose", "Rose"],
  ["amber", "Amber"],
  ["lavender", "Lavender"],
  ["contrast", "High Contrast"],
];

const emptyConnection = {
  tenantId: "",
  clientId: "",
  clientSecret: "",
  subscriptionId: "",
};

function loadConnection() {
  try {
    return { ...emptyConnection, ...(JSON.parse(sessionStorage.getItem(STORAGE_KEY)) || {}) };
  } catch {
    return emptyConnection;
  }
}

function saveConnection(connection) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(connection));
}

function loadTheme() {
  return localStorage.getItem(THEME_KEY) || "light";
}

function azureHeaders(connection) {
  return {
    "x-azure-tenant-id": connection.tenantId,
    "x-azure-client-id": connection.clientId,
    "x-azure-client-secret": connection.clientSecret,
    "x-azure-subscription-id": connection.subscriptionId,
  };
}

async function apiFetch(path, connection, options = {}) {
  const response = await fetch(`${API}/api/v1${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...azureHeaders(connection),
      ...(options.headers || {}),
    },
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `HTTP ${response.status}`);
  }
  return data;
}

async function optionalFetch(path, connection, fallback) {
  try {
    return await apiFetch(path, connection);
  } catch (err) {
    return typeof fallback === "function" ? fallback(err) : fallback;
  }
}

function normalizeCurrency(currency) {
  const raw = String(currency || "").trim();
  if (!raw || raw === "₹" || raw.toUpperCase() === "RS" || raw.toUpperCase() === "INR") {
    return "INR";
  }
  const code = raw.toUpperCase();
  return /^[A-Z]{3}$/.test(code) ? code : "";
}

function formatMoney(value, currency) {
  const amount = Number(value || 0);
  const code = normalizeCurrency(currency);
  const locale = code === "INR" ? "en-IN" : "en-US";
  const options = {
    maximumFractionDigits: amount >= 1000 ? 0 : 2,
  };
  if (code) {
    options.style = "currency";
    options.currency = code;
  }
  return new Intl.NumberFormat(locale, options).format(amount);
}

function dateInputValue(date) {
  const next = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(next.getTime())) return "";
  return next.toISOString().slice(0, 10);
}

function dateInputOffset(daysBack) {
  const next = new Date();
  next.setDate(next.getDate() - daysBack);
  return dateInputValue(next);
}

function normalizeApprovalItem(approval) {
  if (!approval || typeof approval !== "object") return approval;
  if (!approval.id && approval.approval_id) {
    return { ...approval, id: approval.approval_id };
  }
  return approval;
}

function normalizeApprovals(items) {
  return (items || []).map(normalizeApprovalItem);
}

function EmptyState({ icon: Icon = Cloud, title, text }) {
  return (
    <div className="empty-state">
      <Icon size={28} />
      <strong>{title}</strong>
      {text ? <span>{text}</span> : null}
    </div>
  );
}

function Metric({ icon: Icon, label, value, detail }) {
  return (
    <section className="metric">
      <div className="metric-icon">
        <Icon size={19} />
      </div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        {detail ? <small>{detail}</small> : null}
      </div>
    </section>
  );
}

function Panel({ title, action, children }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function ChartTooltip({ active, payload, label, currency }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <strong>{label}</strong>
      {payload.map((item) => (
        <span key={item.dataKey} style={{ color: item.color }}>
          {item.name || item.dataKey}: {typeof item.value === "number" ? formatMoney(item.value, currency) : item.value}
        </span>
      ))}
    </div>
  );
}

function costDetail(cost) {
  const note = cost?.note || "";
  if (Number(cost?.mtd_spend || 0) > 0 && note.toLowerCase().includes("throttl")) {
    return "Showing cached live Azure cost data";
  }
  if (cost?.data_source === "live") return "Azure Cost Management";
  if (cost?.data_source === "cached") return "Cached live Azure cost data";
  return note;
}

function AzureConnect({ connection, onConnect, theme, setTheme }) {
  const [form, setForm] = useState(connection);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const update = (field) => (event) => setForm((prev) => ({ ...prev, [field]: event.target.value }));

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const status = await apiFetch("/azure/connection", form);
      if (!status.connected) {
        throw new Error(status.error || "Azure did not accept these credentials.");
      }
      saveConnection(form);
      onConnect(form, status);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="connect-page">
      <section className="connect-copy">
        <label className="connect-theme-picker">
          Theme
          <select value={theme} onChange={(event) => setTheme(event.target.value)} aria-label="Choose color theme before login">
            {THEMES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </label>
        <div className="brand-mark">
          <Zap size={22} />
        </div>
        <h1>Azure FinOps + CloudOps command center</h1>
        <p>
          Connect an Azure service principal to query live Cost Management,
          Resource Graph, Advisor, Monitor, LangGraph agents, MCP tools, and
          approval-gated operations.
        </p>
        <div className="connect-visual">
          <img src={heroImage} alt="" />
          <div>
            <strong>Real-time control surface</strong>
            <span>No seeded demo values. Empty Azure responses stay blank until your account returns data.</span>
          </div>
        </div>
        <div className="capability-strip">
          <span><Cloud size={15} /> Live Azure APIs</span>
          <span><Bot size={15} /> Agent routing</span>
          <span><TerminalSquare size={15} /> MCP tools</span>
          <span><ShieldCheck size={15} /> Approval gates</span>
        </div>
      </section>

      <form className="connect-form" onSubmit={submit}>
        <h2>Connect Azure Account</h2>
        <label>
          Tenant ID
          <input value={form.tenantId} onChange={update("tenantId")} required autoComplete="off" />
        </label>
        <label>
          Client ID
          <input value={form.clientId} onChange={update("clientId")} required autoComplete="off" />
        </label>
        <label>
          Client Secret
          <input value={form.clientSecret} onChange={update("clientSecret")} required type="password" autoComplete="off" />
        </label>
        <label>
          Subscription ID
          <input value={form.subscriptionId} onChange={update("subscriptionId")} required autoComplete="off" />
        </label>
        {error ? <div className="form-error"><WifiOff size={15} /> {error}</div> : null}
        <button className="primary-button" type="submit" disabled={saving}>
          {saving ? <Loader2 className="spin" size={17} /> : <KeyRound size={17} />}
          Connect live Azure data
        </button>
        <p className="fine-print">
          Credentials are stored only in this browser session and sent to the FastAPI backend per request.
        </p>
      </form>
    </main>
  );
}

function Dashboard({ connection, snapshot, loading, error, refresh }) {
  const cost = snapshot.cost || {};
  const resources = snapshot.resources || {};
  const anomalies = snapshot.anomalies || {};
  const trend = cost.trend || [];
  const services = Object.entries(cost.by_service || {}).map(([name, amount]) => ({ name, amount }));
  const currency = normalizeCurrency(cost.currency || cost.billing_currency || cost.currency_code);
  const commandCards = [
    ["Cost", "show my azure cost", DollarSign],
    ["CloudOps", "list resources", Server],
    ["Advisor", "show advisor recommendations", ClipboardCheck],
    ["Execution", "stop vm my-vm rg my-resource-group", PlayCircle],
  ];

  return (
    <div className="page-stack">
      <div className="toolbar">
        <div>
          <h1>Live Operations</h1>
          <p>{connection.subscriptionId}</p>
        </div>
        <button className="ghost-button" onClick={refresh} disabled={loading}>
          <RefreshCw className={loading ? "spin" : ""} size={16} />
          Refresh
        </button>
      </div>

      {error ? <div className="error-banner"><WifiOff size={16} /> {error}</div> : null}

      <div className="metrics-grid">
        <Metric icon={IndianRupee} label="Month to date" value={formatMoney(cost.mtd_spend, currency)} detail={costDetail(cost)} />
        <Metric icon={TrendingUp} label="Budget usage" value={`${cost.budget_utilisation_pct ?? 0}%`} detail={cost.budget_monthly ? `${formatMoney(cost.budget_monthly, currency)} monthly budget` : "Budget not configured"} />
        <Metric icon={Server} label="Resources" value={resources.total ?? 0} detail={`${resources.unknown ?? 0} unknown health states`} />
        <Metric icon={AlertTriangle} label="Anomalies" value={anomalies.total ?? 0} detail={anomalies.note || "Isolation Forest on live daily costs"} />
      </div>

      <div className="dashboard-grid">
        <Panel title="Cost Trend">
          {trend.length ? (
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={trend}>
                <defs>
                  <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#2563eb" stopOpacity={0.9} />
                    <stop offset="95%" stopColor="#14b8a6" stopOpacity={0.08} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fill: "#607089", fontSize: 12 }} />
                <YAxis tick={{ fill: "#607089", fontSize: 12 }} />
                <Tooltip content={<ChartTooltip currency={currency} />} />
                <Legend />
                <Area type="monotone" name="Daily cost" dataKey="amount" stroke="#2563eb" strokeWidth={3} fill="url(#costGradient)" dot={{ r: 3, fill: "#2563eb" }} activeDot={{ r: 7, strokeWidth: 2 }} />
                {trend.length > 8 ? <Brush dataKey="date" height={22} stroke="#2563eb" travellerWidth={8} /> : null}
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState title="No cost trend yet" text={cost.note || "Azure returned no daily cost rows."} />
          )}
        </Panel>

        <Panel title="Spend By Service">
          {services.length ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={services}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fill: "#607089", fontSize: 11 }} interval={0} angle={-18} textAnchor="end" height={58} />
                <YAxis tick={{ fill: "#607089", fontSize: 12 }} />
                <Tooltip content={<ChartTooltip currency={currency} />} />
                <Bar dataKey="amount" name="Service cost" radius={[6, 6, 0, 0]}>
                  {services.map((entry, index) => (
                    <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState title="No service spend" text="This stays blank until Azure Cost Management returns service-level rows." />
          )}
        </Panel>
      </div>

      <Panel title="ChatOps Command Center">
        <div className="command-grid">
          {commandCards.map(([title, text, Icon], index) => (
            <div className="command-card" key={title}>
              <span style={{ background: CHART_COLORS[index % CHART_COLORS.length] }}>
                <Icon size={18} />
              </span>
              <div>
                <strong>{title}</strong>
                <small>{text}</small>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function uniqueValues(items, getter) {
  return [...new Set(items.map(getter).filter(Boolean).map(String))].sort((a, b) => a.localeCompare(b));
}

function CostExplorer({ connection, snapshot }) {
  const resources = snapshot.resources?.resources || [];
  const costCurrency = normalizeCurrency(snapshot.cost?.currency || snapshot.cost?.billing_currency || snapshot.cost?.currency_code);
  const [filters, setFilters] = useState({
    startDate: dateInputOffset(30),
    endDate: dateInputValue(new Date()),
    billingService: "",
    resourceGroup: "",
    region: "",
    resourceType: "",
    resourceIds: [],
  });
  const [resourceSearch, setResourceSearch] = useState("");
  const [componentSearch, setComponentSearch] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const groupOptions = uniqueValues(resources, (item) => item.resource_group);
  const regionOptions = uniqueValues(resources, (item) => item.region);
  const typeOptions = useMemo(() => {
    const map = new Map();
    resources.forEach((resource) => {
      const value = resource.raw_type || resource.type;
      if (value) map.set(value, resourceTypeLabel(resource));
    });
    return Array.from(map, ([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label));
  }, [resources]);
  const analysisItems = analysis?.items || [];
  const billingOptions = uniqueSorted([
    ...Object.keys(snapshot.cost?.by_service || {}),
    ...analysisItems.map((item) => item.service),
  ]);
  const baseScopedResources = useMemo(() => (
    resources
      .filter((resource) => {
        if (filters.resourceGroup && resource.resource_group !== filters.resourceGroup) return false;
        if (filters.region && resource.region !== filters.region) return false;
        if (filters.resourceType) {
          const raw = `${resource.raw_type || ""} ${resource.type || ""}`.toLowerCase();
          if (!raw.includes(filters.resourceType.toLowerCase())) return false;
        }
        return true;
      })
  ), [resources, filters.resourceGroup, filters.region, filters.resourceType]);
  const resourceOptions = useMemo(() => (
    baseScopedResources
      .map((resource) => ({ resource, score: resourceSearchScore(resource, resourceSearch) }))
      .filter(({ resource, score }) => {
        if (resourceSearch.trim() && score < 18) return false;
        return true;
      })
      .sort((a, b) => b.score - a.score || String(a.resource.name).localeCompare(String(b.resource.name)))
      .map((item) => item.resource)
  ), [baseScopedResources, resourceSearch]);

  const runAnalysis = useCallback(async () => {
    setLoading(true);
    setError("");
    setAnalysis(null);
    try {
      const scopedIds = filters.resourceIds.length
        ? filters.resourceIds
        : (filters.resourceGroup || filters.region || filters.resourceType)
          ? baseScopedResources.map((resource) => resource.id).filter(Boolean)
          : [];
      const params = new URLSearchParams({
        start_date: filters.startDate,
        end_date: filters.endDate,
        service: filters.billingService,
        resource_group: filters.resourceGroup,
        region: filters.region,
        resource_type: filters.resourceType,
        resource_ids: scopedIds.join(","),
      });
      const nextAnalysis = await apiFetch(`/cost/analysis?${params.toString()}`, connection);
      nextAnalysis.request_filters = { ...filters, resourceIds: scopedIds };
      setAnalysis(nextAnalysis);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [connection, filters, baseScopedResources]);

  useEffect(() => {
    runAnalysis();
  }, [runAnalysis]);

  function updateFilter(field, value) {
    setAnalysis(null);
    setFilters((prev) => ({ ...prev, [field]: value, ...(field === "resourceGroup" || field === "region" || field === "resourceType" ? { resourceIds: [] } : {}) }));
  }

  function toggleResource(id) {
    setAnalysis(null);
    setFilters((prev) => {
      const exists = prev.resourceIds.includes(id);
      return { ...prev, resourceIds: exists ? prev.resourceIds.filter((item) => item !== id) : [...prev.resourceIds, id] };
    });
  }

  const currency = normalizeCurrency(analysis?.currency || costCurrency);
  const byResource = analysis?.by_resource || [];
  const byComponent = analysis?.by_component || [];
  const resourceCostMap = useMemo(() => {
    const map = new Map();
    byResource.forEach((row) => {
      if (row.resource_id) map.set(String(row.resource_id).toLowerCase(), row);
      if (row.resource_name) map.set(String(row.resource_name).toLowerCase(), row);
    });
    return map;
  }, [byResource]);
  const scopedResources = filters.resourceIds.length
    ? resources.filter((item) => filters.resourceIds.includes(item.id))
    : (filters.resourceGroup || filters.region || filters.resourceType)
      ? baseScopedResources
      : [];
  const resourcePlotRows = scopedResources.length
    ? scopedResources.map((resource) => {
        const matched = resourceCostMap.get(String(resource.id || "").toLowerCase()) || resourceCostMap.get(String(resource.name || "").toLowerCase());
        return {
          resource_id: resource.id,
          resource_name: resource.name,
          resource_type: resource.raw_type || resource.type || matched?.resource_type || "unknown",
          resource_group: resource.resource_group || matched?.resource_group || "",
          region: resource.region || matched?.region || "",
          status: resource.status || "",
          amount: Number(matched?.amount || 0),
          has_cost: Boolean(matched),
        };
      })
    : byResource;
  const visibleComponents = byComponent.filter((item) => {
    const needle = normalizeSearch(componentSearch);
    if (!needle) return true;
    return normalizeSearch(`${item.service} ${item.component}`).includes(needle);
  });
  const selectedResources = resources.filter((item) => filters.resourceIds.includes(item.id));
  const selectedCostRows = resourcePlotRows;
  const topResource = [...resourcePlotRows].sort((a, b) => Number(b.amount || 0) - Number(a.amount || 0))[0];
  const topComponent = byComponent[0];

  function resetFilters() {
    setFilters({
      startDate: dateInputOffset(30),
      endDate: dateInputValue(new Date()),
      billingService: "",
      resourceGroup: "",
      region: "",
      resourceType: "",
      resourceIds: [],
    });
    setResourceSearch("");
    setComponentSearch("");
  }

  const windowLabel = analysis?.start_date && analysis?.end_date
    ? `${analysis.start_date} to ${analysis.end_date}`
    : `${filters.startDate || "start"} to ${filters.endDate || "today"}`;

  return (
    <div className="page-stack">
      <div>
        <h1>Cost Explorer</h1>
        <p className="page-subtitle">Filter live Azure usage by resource, service, type, region, and compare selected assets.</p>
      </div>

      <Panel title="Cost Filters" action={<button className="ghost-button" type="button" onClick={runAnalysis} disabled={loading}>{loading ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />} Analyze</button>}>
        {error ? <div className="error-banner"><WifiOff size={16} /> {error}</div> : null}
        <div className="filter-grid cost-filter-grid">
          <label>Start date<input type="date" value={filters.startDate} onChange={(e) => updateFilter("startDate", e.target.value)} /></label>
          <label>End date<input type="date" value={filters.endDate} onChange={(e) => updateFilter("endDate", e.target.value)} /></label>
          <label>Azure service<select value={filters.resourceType} onChange={(e) => updateFilter("resourceType", e.target.value)}><option value="">All Azure services</option>{typeOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          <label>Resource group<select value={filters.resourceGroup} onChange={(e) => updateFilter("resourceGroup", e.target.value)}><option value="">All groups</option>{groupOptions.map((item) => <option key={item}>{item}</option>)}</select></label>
          <label>Region<select value={filters.region} onChange={(e) => updateFilter("region", e.target.value)}><option value="">All regions</option>{regionOptions.map((item) => <option key={item}>{item}</option>)}</select></label>
          <label>Billing category<select value={filters.billingService} onChange={(e) => updateFilter("billingService", e.target.value)}><option value="">All billing categories</option>{billingOptions.map((item) => <option key={item}>{item}</option>)}</select></label>
        </div>
        <div className="explorer-toolbar">
          <div className="resource-search">
            <Search size={16} />
            <input value={resourceSearch} onChange={(event) => setResourceSearch(event.target.value)} placeholder="Search resources with typo tolerance..." />
            <span>{resourceOptions.length}</span>
          </div>
          <button className="ghost-button" type="button" onClick={resetFilters}>Reset filters</button>
        </div>
        <p className="panel-note">
          Choose the calendar window and Azure service first. The resource list below is trimmed to that scope; select chips to compare exact resources.
        </p>
        <div className="resource-chip-list scroll-chips">
          {resourceOptions.slice(0, 80).map((resource) => (
            <button
              type="button"
              className={filters.resourceIds.includes(resource.id) ? "selected" : ""}
              key={resource.id}
              onClick={() => toggleResource(resource.id)}
            >
              {resource.name}<small>{resource.type} | {resource.resource_group}</small>
            </button>
          ))}
          {!resourceOptions.length ? <span className="muted-note">No resource matches the current filters.</span> : null}
        </div>
        {selectedResources.length ? (
          <div className="selected-strip">
            {selectedResources.map((resource) => (
              <button key={resource.id} type="button" onClick={() => toggleResource(resource.id)}>
                {resource.name}<X size={13} />
              </button>
            ))}
          </div>
        ) : null}
        <div className="insight-strip">
          <span>Top resource: <strong>{topResource ? `${topResource.resource_name} (${formatMoney(topResource.amount, currency)})` : "No row yet"}</strong></span>
          <span>Top component: <strong>{topComponent ? `${topComponent.component} (${formatMoney(topComponent.amount, currency)})` : "No row yet"}</strong></span>
          <span>Source: <strong>{analysis?.data_source || "loading"}</strong></span>
        </div>
      </Panel>

      <div className="metrics-grid">
        <Metric icon={IndianRupee} label="Filtered spend" value={formatMoney(analysis?.total, currency)} detail={analysis?.data_source || "Loading"} />
        <Metric icon={Server} label="Resources in scope" value={resourcePlotRows.length} detail={`${byResource.length} with charges, ${filters.resourceIds.length} selected`} />
        <Metric icon={Container} label="Components" value={visibleComponents.length} detail={`${byComponent.length} total components`} />
        <Metric icon={TrendingUp} label="Window" value={windowLabel} detail={analysis?.note || `${analysis?.period_days || ""} day usageDetails window`} />
      </div>

      <div className="dashboard-grid">
        <Panel title="Cost By Resource">
          {resourcePlotRows.length ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={resourcePlotRows.slice(0, 20)}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="resource_name" tick={{ fill: "#607089", fontSize: 11 }} interval={0} angle={-18} textAnchor="end" height={70} />
                <YAxis tick={{ fill: "#607089", fontSize: 12 }} />
                <Tooltip content={<ChartTooltip currency={currency} />} />
                <Bar dataKey="amount" name="Cost" radius={[6, 6, 0, 0]}>{resourcePlotRows.slice(0, 20).map((item, index) => <Cell key={item.resource_id || item.resource_name} fill={item.has_cost === false ? "#94a3b8" : CHART_COLORS[index % CHART_COLORS.length]} />)}</Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : <EmptyState icon={DollarSign} title="No resources in scope" text={analysis?.note || "Choose filters or select resources to plot."} />}
        </Panel>
        <Panel title="Cost By Component">
          <div className="mini-search">
            <Search size={15} />
            <input value={componentSearch} onChange={(event) => setComponentSearch(event.target.value)} placeholder="Filter meters, products, services..." />
          </div>
          {visibleComponents.length ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={visibleComponents.slice(0, 12)}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="component" tick={{ fill: "#607089", fontSize: 11 }} interval={0} angle={-18} textAnchor="end" height={70} />
                <YAxis tick={{ fill: "#607089", fontSize: 12 }} />
                <Tooltip content={<ChartTooltip currency={currency} />} />
                <Bar dataKey="amount" name="Cost" radius={[6, 6, 0, 0]}>{visibleComponents.slice(0, 12).map((item, index) => <Cell key={`${item.service}-${item.component}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />)}</Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : <EmptyState icon={Container} title="No component rows" text={analysis?.note || "UsageDetails did not return component-level charges yet."} />}
        </Panel>
      </div>

      <div className="dashboard-grid two">
        <Panel title={filters.resourceIds.length ? "Selected Resource Comparison" : "Filtered Resource Details"}>
          {selectedCostRows.length ? (
            <div className="cost-row-list">
              {selectedCostRows.slice(0, 14).map((item) => (
                <article key={item.resource_id || item.resource_name} className="cost-row">
                  <div>
                    <strong>{item.resource_name || "Unknown resource"}</strong>
                    <span>{item.resource_type} | {item.resource_group} | {item.region}{item.has_cost === false ? " | no cost rows" : ""}</span>
                  </div>
                  <b>{formatMoney(item.amount, currency)}</b>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState icon={Server} title="No matching resource rows" text="Select resources or loosen filters to compare costs." />
          )}
        </Panel>
        <Panel title="Component Details">
          {visibleComponents.length ? (
            <div className="cost-row-list">
              {visibleComponents.slice(0, 14).map((item) => (
                <article key={`${item.service}-${item.component}`} className="cost-row">
                  <div>
                    <strong>{item.component}</strong>
                    <span>{item.service}</span>
                  </div>
                  <b>{formatMoney(item.amount, currency)}</b>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState icon={Container} title="No component details" text="Try a broader component search." />
          )}
        </Panel>
      </div>
    </div>
  );
}

function normalizeSearch(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function editDistance(a, b) {
  const left = normalizeSearch(a).replace(/\s+/g, "");
  const right = normalizeSearch(b).replace(/\s+/g, "");
  if (!left || !right) return Math.max(left.length, right.length);
  const dp = Array.from({ length: left.length + 1 }, (_, i) => [i]);
  for (let j = 1; j <= right.length; j += 1) dp[0][j] = j;
  for (let i = 1; i <= left.length; i += 1) {
    for (let j = 1; j <= right.length; j += 1) {
      dp[i][j] = Math.min(
        dp[i - 1][j] + 1,
        dp[i][j - 1] + 1,
        dp[i - 1][j - 1] + (left[i - 1] === right[j - 1] ? 0 : 1),
      );
    }
  }
  return dp[left.length][right.length];
}

function resourceSearchText(resource) {
  return [
    resource?.name,
    resource?.type,
    resource?.raw_type,
    resource?.resource_group,
    resource?.region,
    resource?.status,
  ].filter(Boolean).join(" ");
}

function resourceSearchScore(resource, query) {
  const normalizedQuery = normalizeSearch(query);
  if (!normalizedQuery) return 100;
  const haystack = normalizeSearch(resourceSearchText(resource));
  if (haystack.includes(normalizedQuery)) return 100;
  const terms = normalizedQuery.split(/\s+/).filter(Boolean);
  const words = haystack.split(/\s+/).filter(Boolean);
  let score = 0;
  for (const term of terms) {
    const best = words.reduce((min, word) => Math.min(min, editDistance(term, word)), 99);
    if (best <= 1) score += 34;
    else if (best <= 2) score += 22;
    else if (words.some((word) => word.startsWith(term.slice(0, 3)))) score += 18;
  }
  return score;
}

function uniqueSorted(items) {
  return Array.from(new Set(items.filter(Boolean))).sort((a, b) => String(a).localeCompare(String(b)));
}

function resourceTypeLabel(resource) {
  return resource?.type || resource?.raw_type || "Unknown";
}

function countBy(items, selector, limit = 10) {
  return Object.entries(items.reduce((acc, item) => {
    const key = selector(item) || "Unknown";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {}))
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
    .slice(0, limit);
}

function CloudOps({ snapshot, connection, refresh }) {
  const resources = useMemo(() => snapshot.resources?.resources || [], [snapshot.resources?.resources]);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState({ type: "", group: "", region: "", status: "" });
  const typeOptions = useMemo(() => uniqueSorted(resources.map(resourceTypeLabel)), [resources]);
  const groupOptions = useMemo(() => uniqueSorted(resources.map((resource) => resource.resource_group)), [resources]);
  const regionOptions = useMemo(() => uniqueSorted(resources.map((resource) => resource.region)), [resources]);
  const statusOptions = useMemo(() => uniqueSorted(resources.map((resource) => resource.status || "unknown")), [resources]);
  const filteredResources = useMemo(() => (
    resources
      .map((resource) => ({ resource, score: resourceSearchScore(resource, query) }))
      .filter((item) => !query.trim() || item.score >= 18)
      .filter(({ resource }) => !filters.type || resourceTypeLabel(resource) === filters.type)
      .filter(({ resource }) => !filters.group || resource.resource_group === filters.group)
      .filter(({ resource }) => !filters.region || resource.region === filters.region)
      .filter(({ resource }) => !filters.status || (resource.status || "unknown") === filters.status)
      .sort((a, b) => b.score - a.score || String(a.resource.name).localeCompare(String(b.resource.name)))
      .map((item) => item.resource)
  ), [resources, query, filters]);
  const recs = snapshot.recommendations?.recommendations || [];
  const guardrails = snapshot.guardrails || { protected_resources: [], spend_rules: [], chat_mutations_enabled: true };
  const [guardrailMessage, setGuardrailMessage] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [inlineApprovals, setInlineApprovals] = useState({});
  const [resourceFeedback, setResourceFeedback] = useState({});
  const [unprotectForm, setUnprotectForm] = useState({ resourceId: "", clientId: "", clientSecret: "" });
  const [protectForm, setProtectForm] = useState({ resourceId: "", action: "all" });
  const [spendRule, setSpendRule] = useState({ resourceId: "", action: "", amount: "4000", pct: "30" });
  const typeData = countBy(resources, resourceTypeLabel);
  const regionData = countBy(resources, (resource) => resource.region);
  const groupData = countBy(resources, (resource) => resource.resource_group);
  const statusData = countBy(resources, (resource) => resource.status || "unknown", 6);
  const actionableResources = resources.filter((resource) => ["vm", "app", "containerapp", "storage"].includes(resourceTypeBucket(resource)));
  const selectedGuardrailResource = resources.find((item) => item.id === protectForm.resourceId);
  const selectedSpendResource = resources.find((item) => item.id === spendRule.resourceId);
  const guardrailActionOptions = selectedGuardrailResource ? [{ key: "all", label: "All operations", command: "all" }, ...supportedResourceActions(selectedGuardrailResource)] : [];
  const spendActionOptions = selectedSpendResource ? supportedResourceActions(selectedSpendResource).filter((item) => ["stop", "scale"].includes(item.key)) : [];

  function commandFor(resource, action) {
    const bucket = resourceTypeBucket(resource);
    const name = resource.name;
    const rg = resource.resource_group;
    if (action === "delete") return `delete azure resource ${name} resource_id ${resource.id} rg ${rg}`;
    if (bucket === "vm") return `${action} vm ${name} rg ${rg}`;
    if (bucket === "app") return `${action} app service ${name} rg ${rg}`;
    if (bucket === "containerapp") return `scale container app ${name} min 1 max 3 rg ${rg}`;
    if (bucket === "storage" && action === "restore") return `restore blob assets/companylogo.png storage_account ${name} rg ${rg}`;
    return "";
  }

  async function proposeResourceAction(resource, action) {
    const message = commandFor(resource, action);
    if (!message) return;
    const actionKey = `${resource.id}-${action}`;
    setBusyAction(actionKey);
    setResourceFeedback((prev) => ({
      ...prev,
      [resource.id]: {
        type: "loading",
        action,
        message: `Creating ${action} approval for ${resource.name}...`,
      },
    }));
    try {
      const strongMessage = `${message}. Create an approval only for this exact requested operation. Do not substitute a delete, resize, or any other action. Exact resource id: ${resource.id}.`;
      const result = await apiFetch("/chat", connection, {
        method: "POST",
        body: JSON.stringify({ message: strongMessage, history: [] }),
      });
      const approval = normalizeApprovalItem(result.actions_proposed?.[0]);
      if (approval?.id) {
        setInlineApprovals((prev) => ({
          ...prev,
          [resource.id]: [approval, ...(prev[resource.id] || []).filter((item) => item.id !== approval.id)].slice(0, 3),
        }));
        setResourceFeedback((prev) => ({
          ...prev,
          [resource.id]: {
            type: "success",
            action,
            message: `Approval ${approval.id} is ready. Approve or reject it here.`,
          },
        }));
      } else {
        setResourceFeedback((prev) => ({
          ...prev,
          [resource.id]: {
            type: result.error ? "error" : "info",
            action,
            message: result.response || "No approval was created for this request.",
          },
        }));
      }
      await refresh?.();
    } catch (err) {
      setResourceFeedback((prev) => ({
        ...prev,
        [resource.id]: {
          type: "error",
          action,
          message: err.message,
        },
      }));
    } finally {
      setBusyAction("");
    }
  }

  async function decideInlineApproval(resourceId, approvalId, decision) {
    const normalizedId = approvalId || "";
    if (!normalizedId) {
      setGuardrailMessage("Approval ID is missing.");
      return;
    }
    setBusyAction(`${normalizedId}-${decision}`);
    setGuardrailMessage("");
    try {
      const result = await apiFetch(`/approvals/${normalizedId}/decide`, connection, {
        method: "POST",
        body: JSON.stringify({ decision, approved_by: "resource-row", notes: "Decided inline from CloudOps resource row" }),
      });
      const detail = result.execution_result?.error || result.execution_result?.message || result.execution_result?.note || "";
      setResourceFeedback((prev) => ({
        ...prev,
        [resourceId]: {
          type: result.execution_succeeded === false ? "error" : "success",
          action: decision,
          message: `${normalizedId} ${decision}. ${detail || result.execution_result?.status || result.status || "recorded"}`.trim(),
        },
      }));
      setInlineApprovals((prev) => ({
        ...prev,
        [resourceId]: (prev[resourceId] || []).filter((item) => item.id !== normalizedId),
      }));
      await refresh?.();
    } catch (err) {
      setResourceFeedback((prev) => ({
        ...prev,
        [resourceId]: {
          type: "error",
          action: decision,
          message: err.message,
        },
      }));
    } finally {
      setBusyAction("");
    }
  }

  async function protect() {
    const resource = resources.find((item) => item.id === protectForm.resourceId);
    if (!resource) return;
    setBusyAction(`${resource.id}-protect`);
    setGuardrailMessage("");
    try {
      await apiFetch("/guardrails/protect", connection, {
        method: "POST",
        body: JSON.stringify({
          ...resource,
          blocked_actions: [protectForm.action || "all"],
          reason: `Protected ${protectForm.action || "all"} operations from CloudOps resource page.`,
        }),
      });
      setGuardrailMessage(`${resource.name} is protected for ${protectForm.action || "all"} operation(s). Matching chat approvals and execution will be blocked.`);
      setProtectForm({ resourceId: "", action: "all" });
      await refresh?.();
    } catch (err) {
      setGuardrailMessage(err.message);
    } finally {
      setBusyAction("");
    }
  }

  async function unprotect() {
    setBusyAction("unprotect");
    setGuardrailMessage("");
    try {
      await apiFetch("/guardrails/unprotect", connection, {
        method: "POST",
        body: JSON.stringify({
          resource_id: unprotectForm.resourceId,
          client_id: unprotectForm.clientId,
          client_secret: unprotectForm.clientSecret,
        }),
      });
      setGuardrailMessage("Protection removed. Changes can now be requested for that resource.");
      setUnprotectForm({ resourceId: "", clientId: "", clientSecret: "" });
      await refresh?.();
    } catch (err) {
      setGuardrailMessage(err.message);
    } finally {
      setBusyAction("");
    }
  }

  async function toggleChatMutations(enabled) {
    setBusyAction("chat-mutations");
    try {
      await apiFetch("/guardrails/chat-mutations", connection, {
        method: "POST",
        body: JSON.stringify({ enabled }),
      });
      setGuardrailMessage(enabled ? "Chat mutation approvals are enabled." : "Chat mutation approvals are blocked by guardrail.");
      await refresh?.();
    } catch (err) {
      setGuardrailMessage(err.message);
    } finally {
      setBusyAction("");
    }
  }

  async function saveSpendRule() {
    const resource = resources.find((item) => item.id === spendRule.resourceId);
    if (!resource) return;
    const selected = supportedResourceActions(resource).find((item) => item.command === spendRule.action) || defaultSpendAction(resource);
    if (!selected) {
      setGuardrailMessage("This resource does not expose a safe automatic spend action yet.");
      return;
    }
    setBusyAction("spend-rule");
    try {
      await apiFetch("/guardrails/spend-rules", connection, {
        method: "POST",
        body: JSON.stringify({
          resource_id: resource.id,
          resource_name: resource.name,
          resource_group: resource.resource_group,
          resource_type: resource.raw_type || resource.type,
          threshold_amount: Number(spendRule.amount || 0),
          threshold_pct: Number(spendRule.pct || 0),
          action: selected.command,
          action_label: selected.label,
          enabled: true,
        }),
      });
      setGuardrailMessage(`Spend guardrail saved for ${resource.name}. If triggered, FinOps.AI will run ${selected.label}.`);
      await refresh?.();
    } catch (err) {
      setGuardrailMessage(err.message);
    } finally {
      setBusyAction("");
    }
  }

  async function evaluateSpendRules() {
    setBusyAction("evaluate-spend");
    try {
      const result = await apiFetch("/guardrails/evaluate-spend", connection, { method: "POST" });
      const triggered = (result.results || []).filter((item) => item.triggered).length;
      setGuardrailMessage(`Spend guardrails evaluated. Triggered rules: ${triggered}.`);
      await refresh?.();
    } catch (err) {
      setGuardrailMessage(err.message);
    } finally {
      setBusyAction("");
    }
  }

  return (
    <div className="page-stack">
      <div>
        <h1>CloudOps Inventory</h1>
        <p className="page-subtitle">Live Azure Resource Graph inventory with fuzzy search, filters, and operation-ready resource context.</p>
      </div>

      <div className="metrics-grid">
        <Metric icon={Server} label="Resources" value={resources.length} detail={`${filteredResources.length} visible after filters`} />
        <Metric icon={Cloud} label="Resource groups" value={groupOptions.length} detail={groupOptions.slice(0, 2).join(", ") || "None"} />
        <Metric icon={Container} label="Regions" value={regionOptions.length} detail={regionOptions.slice(0, 2).join(", ") || "None"} />
        <Metric icon={PlayCircle} label="Operation targets" value={actionableResources.length} detail="VM, App Service, Container App, Storage" />
      </div>

      <Panel title="Guardrails">
        {guardrailMessage ? <div className="info-banner">{guardrailMessage}</div> : null}
        <div className="guardrail-grid">
          <div className="guardrail-card">
            <strong>Chat mutations</strong>
            <span>{guardrails.chat_mutations_enabled ? "AI chat can create approvals." : "AI chat cannot create mutation approvals."}</span>
            <button className="ghost-button" type="button" onClick={() => toggleChatMutations(!guardrails.chat_mutations_enabled)} disabled={Boolean(busyAction)}>
              {guardrails.chat_mutations_enabled ? "Block chat changes" : "Allow chat changes"}
            </button>
          </div>
          <div className="guardrail-card">
            <strong>Block operations</strong>
            <span>Choose a live resource and the exact operation to block. Matching chat approvals and execution are rejected.</span>
            <select value={protectForm.resourceId} onChange={(event) => setProtectForm({ resourceId: event.target.value, action: "all" })}>
              <option value="">Choose live resource</option>
              {resources.map((item) => <option key={item.id} value={item.id}>{item.name} ({item.type})</option>)}
            </select>
            <select value={protectForm.action} onChange={(event) => setProtectForm((prev) => ({ ...prev, action: event.target.value }))} disabled={!selectedGuardrailResource}>
              <option value="">Choose operation</option>
              {guardrailActionOptions.map((item) => <option key={item.command || item.key} value={item.command || item.key}>{item.label}</option>)}
            </select>
            <button className="ghost-button" type="button" onClick={protect} disabled={!protectForm.resourceId || !protectForm.action || Boolean(busyAction)}>Block selected operation</button>
          </div>
          <div className="guardrail-card">
            <strong>Protected rules</strong>
            <span>{(guardrails.protected_resources || []).length} operation guardrail(s) active. Turn off requires Azure client ID and secret.</span>
            <select value={unprotectForm.resourceId} onChange={(event) => setUnprotectForm((prev) => ({ ...prev, resourceId: event.target.value }))}>
              <option value="">Choose protected rule</option>
              {(guardrails.protected_resources || []).map((item) => (
                <option key={`${item.id}-${(item.blocked_actions || []).join("-")}`} value={item.id}>
                  {item.name} - {(item.blocked_actions || ["all"]).join(", ")}
                </option>
              ))}
            </select>
            <input value={unprotectForm.clientId} onChange={(event) => setUnprotectForm((prev) => ({ ...prev, clientId: event.target.value }))} placeholder="Azure client ID" />
            <input value={unprotectForm.clientSecret} onChange={(event) => setUnprotectForm((prev) => ({ ...prev, clientSecret: event.target.value }))} placeholder="Azure client secret" type="password" />
            <button className="ghost-button" type="button" onClick={unprotect} disabled={!unprotectForm.resourceId || !unprotectForm.clientId || !unprotectForm.clientSecret || Boolean(busyAction)}>Turn protection off</button>
          </div>
          <div className="guardrail-card">
            <strong>Spend auto-action</strong>
            <span>Choose any live resource. Supported actions appear dynamically for that resource type.</span>
            <select value={spendRule.resourceId} onChange={(event) => {
              const resource = resources.find((item) => item.id === event.target.value);
              const action = resource ? defaultSpendAction(resource)?.command || "" : "";
              setSpendRule((prev) => ({ ...prev, resourceId: event.target.value, action }));
            }}>
              <option value="">Choose resource</option>
              {resources.map((item) => <option key={item.id} value={item.id}>{item.name} ({item.type})</option>)}
            </select>
            <select value={spendRule.action} onChange={(event) => setSpendRule((prev) => ({ ...prev, action: event.target.value }))} disabled={!selectedSpendResource || !spendActionOptions.length}>
              <option value="">{selectedSpendResource && !spendActionOptions.length ? "No supported spend action" : "Choose action"}</option>
              {spendActionOptions.map((item) => <option key={item.command} value={item.command}>{item.label}</option>)}
            </select>
            <input value={spendRule.amount} onChange={(event) => setSpendRule((prev) => ({ ...prev, amount: event.target.value }))} placeholder="Amount threshold, e.g. 4000" />
            <input value={spendRule.pct} onChange={(event) => setSpendRule((prev) => ({ ...prev, pct: event.target.value }))} placeholder="Percent threshold, e.g. 30" />
            <div className="approval-actions">
              <button className="approve-button" type="button" onClick={saveSpendRule} disabled={!spendRule.resourceId || !spendRule.action || Boolean(busyAction)}>Save rule</button>
              <button className="ghost-button" type="button" onClick={evaluateSpendRules} disabled={Boolean(busyAction)}>Evaluate now</button>
            </div>
          </div>
        </div>
      </Panel>

      <Panel title="Resources">
        <div className="resource-search">
          <Search size={17} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search resources, type, group, region, or try a typo..."
          />
          <span>{filteredResources.length}/{resources.length}</span>
        </div>
        <div className="resource-filters">
          <label>Type<select value={filters.type} onChange={(event) => setFilters((prev) => ({ ...prev, type: event.target.value }))}><option value="">All types</option>{typeOptions.map((item) => <option key={item}>{item}</option>)}</select></label>
          <label>Group<select value={filters.group} onChange={(event) => setFilters((prev) => ({ ...prev, group: event.target.value }))}><option value="">All groups</option>{groupOptions.map((item) => <option key={item}>{item}</option>)}</select></label>
          <label>Region<select value={filters.region} onChange={(event) => setFilters((prev) => ({ ...prev, region: event.target.value }))}><option value="">All regions</option>{regionOptions.map((item) => <option key={item}>{item}</option>)}</select></label>
          <label>Status<select value={filters.status} onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}><option value="">All states</option>{statusOptions.map((item) => <option key={item}>{item}</option>)}</select></label>
          <button className="ghost-button" type="button" onClick={() => { setQuery(""); setFilters({ type: "", group: "", region: "", status: "" }); }}>Reset</button>
        </div>
        {resources.length ? (
          <div className="resource-table">
            {filteredResources.map((resource) => (
              <div className="resource-row" key={resource.id}>
                <Server size={17} />
                <div>
                  <strong>{resource.name}</strong>
                  <span>{resource.type} | {resource.resource_group} | {resource.region}</span>
                  <small>{resource.id}</small>
                  <div className="resource-actions">
                    {supportedResourceActions(resource).map((action) => (
                      <button
                        key={action.command}
                        type="button"
                        className={action.destructive ? "danger-action" : ""}
                        onClick={() => proposeResourceAction(resource, action.key)}
                        disabled={Boolean(busyAction)}
                      >
                        {busyAction === `${resource.id}-${action.key}` ? <Loader2 className="spin" size={13} /> : null}
                        {action.label}
                      </button>
                    ))}
                  </div>
                  {resourceFeedback[resource.id] ? (
                    <div className={`resource-feedback ${resourceFeedback[resource.id].type}`}>
                      {resourceFeedback[resource.id].type === "loading" ? <Loader2 className="spin" size={15} /> : null}
                      <span>{resourceFeedback[resource.id].message}</span>
                    </div>
                  ) : null}
                  {(inlineApprovals[resource.id] || []).map((approval) => {
                    const approvalId = approval.id || approval.approval_id;
                    return (
                      <div className="inline-approval" key={approvalId}>
                        <div>
                          <strong>{approval.action || approval.action_type}</strong>
                          <span>{approvalId} | {approval.risk || "Medium"} risk</span>
                        </div>
                        <button className="approve-button" type="button" onClick={() => decideInlineApproval(resource.id, approvalId, "approved")} disabled={Boolean(busyAction)}>
                          <CheckCircle2 size={14} /> Approve
                        </button>
                        <button className="reject-button" type="button" onClick={() => decideInlineApproval(resource.id, approvalId, "rejected")} disabled={Boolean(busyAction)}>
                          <XCircle size={14} /> Reject
                        </button>
                      </div>
                    );
                  })}
                </div>
                <small className={`status-pill status-${String(resource.status || "unknown").toLowerCase()}`}>{resource.status || "unknown"}</small>
              </div>
            ))}
          </div>
        ) : null}
        {resources.length && !filteredResources.length ? (
          <EmptyState icon={Search} title="No matching resources" text="Try a resource type, partial name, region, or resource group." />
        ) : (
          !resources.length ? (
          <EmptyState icon={Server} title="No resources returned" text="Resource Graph returned an empty inventory for this subscription." />
          ) : null
        )}
      </Panel>

      <div className="dashboard-grid two">
        <Panel title="Resource Mix">
          {typeData.length ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={typeData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fill: "#607089", fontSize: 11 }} interval={0} angle={-18} textAnchor="end" height={72} />
                <YAxis allowDecimals={false} tick={{ fill: "#607089", fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="count" name="Resources" radius={[6, 6, 0, 0]}>
                  {typeData.map((entry, index) => (
                    <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState icon={Server} title="No resource mix yet" text="Resource Graph returned no resources to visualize." />
          )}
        </Panel>

        <Panel title="Resources By Region">
          {regionData.length ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={regionData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fill: "#607089", fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fill: "#607089", fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="count" name="Resources" radius={[6, 6, 0, 0]}>
                  {regionData.map((entry, index) => (
                    <Cell key={entry.name} fill={CHART_COLORS[(index + 2) % CHART_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState icon={Cloud} title="No region data" text="Resource Graph returned no resource locations." />
          )}
        </Panel>

        <Panel title="Resources By Group">
          {groupData.length ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={groupData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fill: "#607089", fontSize: 11 }} interval={0} angle={-18} textAnchor="end" height={72} />
                <YAxis allowDecimals={false} tick={{ fill: "#607089", fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="count" name="Resources" radius={[6, 6, 0, 0]}>
                  {groupData.map((entry, index) => (
                    <Cell key={entry.name} fill={CHART_COLORS[(index + 4) % CHART_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState icon={Container} title="No group data" text="Resource Graph returned no resource groups." />
          )}
        </Panel>

        <Panel title="Health State">
          {statusData.length ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={statusData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fill: "#607089", fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fill: "#607089", fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="count" name="Resources" radius={[6, 6, 0, 0]}>
                  {statusData.map((entry, index) => (
                    <Cell key={entry.name} fill={CHART_COLORS[(index + 1) % CHART_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState icon={ShieldCheck} title="No health state data" text="Health state is unavailable for these resources." />
          )}
        </Panel>
      </div>

      <Panel title="Advisor Recommendations">
        {recs.length ? (
          <div className="recommendation-list">
            {recs.map((rec) => (
              <article className="recommendation" key={rec.id || `${rec.resource}-${rec.problem}`}>
                <strong>{rec.short_description || rec.problem || "Azure Advisor recommendation"}</strong>
                <span>{rec.category || "Advisor"} | {rec.impact || "Impact not supplied"}</span>
                <small>{rec.resource || "Resource not supplied"}</small>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState icon={CheckCircle2} title="No Advisor recommendations" text="Azure Advisor returned no recommendations for this subscription." />
        )}
      </Panel>
    </div>
  );
}

function SecurityPage({ snapshot }) {
  const security = snapshot.security?.security || {};
  const policy = snapshot.security?.policy || {};
  const findings = security.findings || [];
  const policyItems = policy.items || [];
  const postureData = [
    { name: "Security findings", count: Number(security.total || 0) },
    { name: "Policy issues", count: Number(policy.total_non_compliant || 0) },
  ];

  return (
    <div className="page-stack">
      <div>
        <h1>Security & Governance</h1>
        <p className="page-subtitle">Live Defender for Cloud Resource Graph findings and Azure Policy compliance.</p>
        {security.note ? <p className="panel-note">{security.note}</p> : null}
      </div>

      <div className="metrics-grid">
        <Metric icon={ShieldCheck} label="Security findings" value={security.total ?? 0} detail={security.data_source || "Not loaded"} />
        <Metric icon={CheckSquare} label="Policy issues" value={policy.total_non_compliant ?? 0} detail={policy.data_source || "Not loaded"} />
        <Metric icon={Cloud} label="Defender source" value={security.data_source || "unknown"} detail={security.note || "Resource Graph securityresources"} />
        <Metric icon={ClipboardCheck} label="Policy source" value={policy.data_source || "unknown"} detail={policy.note || "Azure Policy Insights"} />
      </div>

      <Panel title="Security Posture">
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={postureData}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
            <XAxis dataKey="name" tick={{ fill: "#607089", fontSize: 12 }} />
            <YAxis allowDecimals={false} tick={{ fill: "#607089", fontSize: 12 }} />
            <Tooltip />
            <Bar dataKey="count" name="Count" radius={[6, 6, 0, 0]}>
              {postureData.map((entry, index) => (
                <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <Panel title="Defender Findings">
        {findings.length ? (
          <div className="recommendation-list">
            {findings.slice(0, 20).map((item) => (
              <article className="recommendation" key={item.id || item.name}>
                <strong>{item.properties?.displayName || item.name || item.id}</strong>
                <span>
                  {item.is_demo ? "Demo finding | " : ""}
                  {item.severity || item.properties?.metadata?.severity || "Severity unknown"} | {item.properties?.status?.code || item.type || "securityresources"}
                </span>
                <small>{item.id}</small>
                {item.properties?.remediationDescription ? <small>{item.properties.remediationDescription}</small> : null}
              </article>
            ))}
          </div>
        ) : (
          <EmptyState icon={ShieldCheck} title="No Defender findings returned" text={security.note || "The subscription returned no securityresources rows."} />
        )}
      </Panel>

      <Panel title="Policy Compliance">
        {policyItems.length ? (
          <div className="recommendation-list">
            {policyItems.slice(0, 20).map((item) => (
              <article className="recommendation" key={`${item.assignment}-${item.resource_id}`}>
                <strong>{item.definition || item.assignment || "Policy finding"}</strong>
                <span>{item.compliance_state || "Unknown"}</span>
                <small>{item.resource_id}</small>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState icon={CheckSquare} title="No policy issues returned" text={policy.note || "Azure Policy returned no non-compliant resources."} />
        )}
      </Panel>
    </div>
  );
}

function ForecastPage({ snapshot }) {
  const forecast = snapshot.forecast || {};
  const points = forecast.series || [];
  const currency = normalizeCurrency(forecast.currency || snapshot.cost?.currency || snapshot.cost?.billing_currency || snapshot.cost?.currency_code);

  return (
    <div className="page-stack">
      <div>
        <h1>Cost Forecast</h1>
        <p className="page-subtitle">Live Azure spend projection with average, linear, and XGBoost modes as history grows.</p>
      </div>
      <Panel title="30 Day Forecast">
        {forecast.note ? <p className="panel-note">{forecast.note}</p> : null}
        {points.length ? (
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={points}>
              <defs>
                <linearGradient id="forecastGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#7c3aed" stopOpacity={0.85} />
                  <stop offset="95%" stopColor="#f97316" stopOpacity={0.08} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fill: "#607089", fontSize: 12 }} />
              <YAxis tick={{ fill: "#607089", fontSize: 12 }} />
              <Tooltip content={<ChartTooltip currency={currency} />} />
              <Legend />
              <Area type="monotone" name="Actual spend" dataKey="actual" stroke="#2563eb" strokeWidth={3} fill="transparent" dot={{ r: 3, fill: "#2563eb" }} activeDot={{ r: 7 }} />
              <Area type="monotone" name="Predicted spend" dataKey="predicted" stroke="#7c3aed" strokeWidth={3} fill="url(#forecastGradient)" dot={{ r: 3, fill: "#7c3aed" }} activeDot={{ r: 7 }} />
              {points.some((point) => point.hi != null) ? <Area type="monotone" name="Upper bound" dataKey="hi" stroke="#f97316" strokeDasharray="5 5" fill="transparent" dot={false} /> : null}
              {points.length > 8 ? <Brush dataKey="date" height={22} stroke="#7c3aed" travellerWidth={8} /> : null}
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <EmptyState icon={TrendingUp} title="Forecast not available" text={forecast.note || "Azure has not returned enough daily cost history yet."} />
        )}
      </Panel>
    </div>
  );
}

function AnomalyPage({ snapshot }) {
  const anomalies = snapshot.anomalies?.items || [];
  const cost = snapshot.cost || {};
  const trend = cost.trend || [];
  const currency = normalizeCurrency(cost.currency || cost.billing_currency || cost.currency_code);
  const severityData = countBy(anomalies, (item) => item.severity || "normal", 6);
  const anomalyScoreData = anomalies.map((item, index) => ({
    name: item.date || item.title || `A${index + 1}`,
    score: Math.abs(Number(item.ml_score || item.score || 0)),
    amount: Number(item.amount || item.cost || 0),
  }));

  return (
    <div className="page-stack">
      <div>
        <h1>Anomalies</h1>
        <p className="page-subtitle">Isolation Forest detections from live Azure cost trend data.</p>
      </div>
      <div className="dashboard-grid two">
        <Panel title="Daily Cost Signal">
          {trend.length ? (
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={trend}>
                <defs>
                  <linearGradient id="anomalyCostGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#e11d48" stopOpacity={0.55} />
                    <stop offset="95%" stopColor="#14b8a6" stopOpacity={0.08} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fill: "#607089", fontSize: 12 }} />
                <YAxis tick={{ fill: "#607089", fontSize: 12 }} />
                <Tooltip content={<ChartTooltip currency={currency} />} />
                <Area type="monotone" name="Daily cost" dataKey="amount" stroke="#e11d48" strokeWidth={3} fill="url(#anomalyCostGradient)" dot={{ r: 3, fill: "#e11d48" }} activeDot={{ r: 7 }} />
                {trend.length > 8 ? <Brush dataKey="date" height={22} stroke="#e11d48" travellerWidth={8} /> : null}
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState icon={AlertTriangle} title="No cost signal yet" text={cost.note || "Cost trend has not returned daily rows yet."} />
          )}
        </Panel>
        <Panel title="Anomaly Severity Mix">
          {severityData.length ? (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={severityData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fill: "#607089", fontSize: 12 }} />
                <YAxis allowDecimals={false} tick={{ fill: "#607089", fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="count" name="Detections" radius={[6, 6, 0, 0]}>
                  {severityData.map((entry, index) => <Cell key={entry.name} fill={CHART_COLORS[(index + 3) % CHART_COLORS.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState icon={ShieldCheck} title="No severity records" text="When anomalies exist, this chart separates warning and critical detections." />
          )}
        </Panel>
      </div>
      <Panel title="Anomaly Score Timeline">
        {anomalyScoreData.length ? (
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={anomalyScoreData}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
              <XAxis dataKey="name" tick={{ fill: "#607089", fontSize: 12 }} />
              <YAxis tick={{ fill: "#607089", fontSize: 12 }} />
              <Tooltip content={<ChartTooltip currency={currency} />} />
              <Bar dataKey="score" name="Model score" fill="#7c3aed" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <EmptyState icon={TrendingUp} title="No model scores yet" text={snapshot.anomalies?.note || "Isolation Forest needs at least five daily cost points."} />
        )}
      </Panel>
      <Panel title="Detected Anomalies">
        {anomalies.length ? (
          <div className="recommendation-list">
            {anomalies.map((item) => (
              <article className="recommendation" key={item.id || `${item.title}-${item.resource}`}>
                <strong>{item.title}</strong>
                <span>{item.severity} | {item.delta || "No delta supplied"}</span>
                <small>{item.resource}</small>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState icon={AlertTriangle} title="No anomalies" text={snapshot.anomalies?.note || "No live anomaly records were returned."} />
        )}
      </Panel>
    </div>
  );
}

function ApprovalsPage({ snapshot, connection, refresh }) {
  const snapshotApprovals = snapshot.approvals?.items || [];
  const [approvals, setApprovals] = useState(snapshotApprovals);
  const [filters, setFilters] = useState({ query: "", status: "active", days: "30", includeArchived: false });
  const [auditEntries, setAuditEntries] = useState([]);
  const [auditFilters, setAuditFilters] = useState({ query: "", days: "30" });
  const [deciding, setDeciding] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    setApprovals(snapshotApprovals);
  }, [snapshotApprovals]);

  async function loadApprovals(includeArchived = filters.includeArchived) {
    try {
      const result = await apiFetch(`/approvals/?include_archived=${includeArchived ? "true" : "false"}`, connection);
      setApprovals(result.items || []);
    } catch (err) {
      setMessage(err.message);
    }
  }

  async function loadAudit() {
    try {
      const result = await apiFetch("/approvals/audit/log?limit=200", connection);
      setAuditEntries(result.entries || []);
    } catch {
      setAuditEntries([]);
    }
  }

  useEffect(() => {
    loadAudit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function decide(id, decision) {
    setDeciding(`${id}-${decision}`);
    setMessage("");
    try {
      const result = await apiFetch(`/approvals/${id}/decide`, connection, {
        method: "POST",
        body: JSON.stringify({ decision, approved_by: "web-ui", notes: "Decided from dashboard" }),
      });
      const status = result.execution_result?.status || result.status || "recorded";
      const detail = result.execution_result?.error || result.execution_result?.note || result.execution_result?.message || "";
      if (decision === "approved" && result.execution_succeeded === false) {
        setMessage(`${id} could not execute and is still pending. ${detail || `Execution status: ${status}.`}`);
      } else {
        setMessage(`${id} ${decision}. Execution status: ${status}.${detail ? ` ${detail}` : ""}`);
      }
      await refresh();
      await loadApprovals(filters.includeArchived);
      await loadAudit();
    } catch (err) {
      setMessage(err.message);
    } finally {
      setDeciding("");
    }
  }

  async function archive(id) {
    setDeciding(`${id}-archive`);
    setMessage("");
    try {
      await apiFetch(`/approvals/${id}/archive`, connection, {
        method: "POST",
        body: JSON.stringify({ archived_by: "web-ui", reason: "Archived from approval log cleanup" }),
      });
      setMessage(`${id} archived.`);
      await refresh();
      await loadApprovals(filters.includeArchived);
      await loadAudit();
    } catch (err) {
      setMessage(err.message);
    } finally {
      setDeciding("");
    }
  }

  const visibleApprovals = approvals.filter((item) => {
    const query = normalizeSearch(filters.query);
    if (query && !normalizeSearch(`${item.id} ${item.action} ${item.action_type} ${item.resource} ${item.status} ${item.risk}`).includes(query)) {
      return false;
    }
    if (filters.status === "pending" && item.status !== "pending") return false;
    if (filters.status === "approved" && item.status !== "approved") return false;
    if (filters.status === "rejected" && item.status !== "rejected") return false;
    if (filters.status === "archived" && !item.archived) return false;
    if (filters.status === "active" && item.archived) return false;
    if (filters.days !== "all") {
      const created = Date.parse(item.created_at || item.decided_at || item.archived_at || "");
      if (Number.isFinite(created)) {
        const ageMs = Date.now() - created;
        if (ageMs > Number(filters.days) * 24 * 60 * 60 * 1000) return false;
      }
    }
    return true;
  });
  const visibleAudit = auditEntries.filter((item) => {
    const query = normalizeSearch(auditFilters.query);
    if (query && !normalizeSearch(`${item.event_type} ${item.actor} ${item.resource} ${item.action} ${item.outcome} ${item.detail} ${item.approval_id}`).includes(query)) {
      return false;
    }
    if (auditFilters.days !== "all") {
      const ts = Date.parse(item.timestamp || "");
      if (Number.isFinite(ts) && Date.now() - ts > Number(auditFilters.days) * 24 * 60 * 60 * 1000) return false;
    }
    return true;
  });

  return (
    <div className="page-stack">
      <div>
        <h1>Approvals</h1>
        <p className="page-subtitle">Approval-gated execution queue. Approve real actions here or from the chatbot.</p>
      </div>
      <Panel title="Pending Actions">
        {message ? <div className="info-banner">{message}</div> : null}
        <div className="log-toolbar">
          <div className="mini-search">
            <Search size={15} />
            <input value={filters.query} onChange={(event) => setFilters((prev) => ({ ...prev, query: event.target.value }))} placeholder="Search approvals, resources, status..." />
          </div>
          <select value={filters.status} onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}>
            <option value="active">Active</option>
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="archived">Archived</option>
            <option value="all">All</option>
          </select>
          <select value={filters.days} onChange={(event) => setFilters((prev) => ({ ...prev, days: event.target.value }))}>
            <option value="7">Last 7 days</option>
            <option value="30">Last 30 days</option>
            <option value="90">Last 90 days</option>
            <option value="all">All time</option>
          </select>
          <button
            className="ghost-button"
            type="button"
            onClick={async () => {
              const next = !filters.includeArchived;
              setFilters((prev) => ({ ...prev, includeArchived: next, status: next ? "all" : "active" }));
              await loadApprovals(next);
            }}
          >
            {filters.includeArchived ? "Hide archived" : "Show archived"}
          </button>
        </div>
        {visibleApprovals.length ? (
          <div className="recommendation-list">
            {visibleApprovals.map((item) => (
              <article className="recommendation" key={item.id}>
                <strong>{item.action}</strong>
                <span>{item.risk} risk | {item.projected_savings || "No savings estimate"} | {item.status}{item.archived ? " | archived" : ""}</span>
                <small>{item.resource}</small>
                {item.last_execution_result ? (
                  <small className="execution-note">
                    Last execution: {item.last_execution_result.status || (item.last_execution_result.success ? "success" : "failed")}
                    {item.last_execution_result.error ? ` - ${item.last_execution_result.error}` : ""}
                  </small>
                ) : null}
                {item.status === "pending" ? (
                  <div className="approval-actions">
                    <button className="approve-button" onClick={() => decide(item.id, "approved")} disabled={Boolean(deciding)}>
                      {deciding === `${item.id}-approved` ? <Loader2 className="spin" size={15} /> : <CheckCircle2 size={15} />}
                      Approve
                    </button>
                    <button className="reject-button" onClick={() => decide(item.id, "rejected")} disabled={Boolean(deciding)}>
                      {deciding === `${item.id}-rejected` ? <Loader2 className="spin" size={15} /> : <XCircle size={15} />}
                      Reject
                    </button>
                  </div>
                ) : null}
                {!item.archived ? (
                  <button className="ghost-button compact-button" onClick={() => archive(item.id)} disabled={Boolean(deciding)}>
                    Archive
                  </button>
                ) : null}
              </article>
            ))}
          </div>
        ) : (
          <EmptyState icon={CheckSquare} title="No approval records match" text="Try a wider date range, status filter, or show archived records." />
        )}
      </Panel>
      <Panel title="Approval & Execution Logs">
        <div className="log-toolbar">
          <div className="mini-search">
            <Search size={15} />
            <input value={auditFilters.query} onChange={(event) => setAuditFilters((prev) => ({ ...prev, query: event.target.value }))} placeholder="Search logs by actor, resource, action, outcome..." />
          </div>
          <select value={auditFilters.days} onChange={(event) => setAuditFilters((prev) => ({ ...prev, days: event.target.value }))}>
            <option value="7">Last 7 days</option>
            <option value="30">Last 30 days</option>
            <option value="90">Last 90 days</option>
            <option value="all">All time</option>
          </select>
          <button className="ghost-button" type="button" onClick={loadAudit}>Refresh logs</button>
        </div>
        {visibleAudit.length ? (
          <div className="cost-row-list">
            {visibleAudit.slice(0, 80).map((entry) => (
              <article className="cost-row" key={entry.id}>
                <div>
                  <strong>{entry.event_type} | {entry.outcome}</strong>
                  <span>{entry.action} on {entry.resource}</span>
                  <small>{entry.actor} | {entry.timestamp}</small>
                </div>
                <b>{entry.approval_id || "audit"}</b>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState icon={ClipboardCheck} title="No logs match" text="Try a wider date range or a simpler search term." />
        )}
      </Panel>
    </div>
  );
}
function Architecture() {
  const workflow = [
    {
      title: "Connect Azure Account",
      actor: "User + React",
      files: "App.jsx -> routers/azure.py -> services/azure_account.py",
      detail: "The user enters tenant, client, secret, and subscription details. React stores them in sessionStorage and sends x-azure-* headers on every API call. FastAPI binds those headers to a per-request AzureAccount ContextVar.",
      output: "Connection card, resource count, live subscription ID.",
    },
    {
      title: "Load Live Operations",
      actor: "Dashboard + FastAPI",
      files: "routers/cost.py, cloudops.py, forecast.py, anomalies.py, security.py",
      detail: "The dashboard fetches cost, resources, approvals, recommendations, security posture, forecast, and anomalies in parallel. Cost data is cached and falls back to Consumption usageDetails when Cost Management throttles.",
      output: "INR cost cards, resource inventory, charts, anomaly count, security cards.",
    },
    {
      title: "Ask ChatOps",
      actor: "LangGraph + Agents",
      files: "routers/chat.py -> agents/langgraph_orchestrator.py -> agents/*",
      detail: "Chat first tries the LangGraph supervisor. The supervisor can route one request to FinOps, CloudOps, Security, Forecast, Anomaly, Approval, or Remediation specialists. If Azure OpenAI fails, direct ChatOps tools still answer with live Azure data.",
      output: "Natural-language answer, tool results, proposed approvals.",
    },
    {
      title: "Use MCP Tools",
      actor: "Tool Registry",
      files: "mcp_layer/tool_registry.py + mcp_layer/*_server/tools.py",
      detail: "Tools are grouped into FinOps, CloudOps, Execution, Knowledge, Notification, Monitoring, and Security capabilities. Read tools fetch live data. Execution tools require approval before Azure mutations happen.",
      output: "Cost summaries, resource lists, security findings, executable remediation actions.",
    },
    {
      title: "Approve Operation",
      actor: "Human Approval",
      files: "routers/approvals.py -> services/approval_execution_service.py -> agents/remediation_agent.py",
      detail: "Approvals are transactional and appear where the request was created: inside ChatOps, on the Approvals page, or directly below the clicked CloudOps resource row. The clicked resource row shows loading, success, or error feedback locally.",
      output: "Inline approve/reject controls, row-local errors, audit log, pending retry state when Azure rejects execution.",
    },
    {
      title: "Execute In Azure",
      actor: "Azure SDK / REST",
      files: "mcp_layer/execution_server/tools.py",
      detail: "The execution server runs VM, App Service, Container App, Storage, and generic ARM operations using the service principal. ARM IDs are parsed into resource group and resource name automatically.",
      output: "Real Azure operation result. Verified live: App Service restart, stop, and start on madhu.",
    },
    {
      title: "Govern, Audit, Improve",
      actor: "Governance + UI",
      files: "agents/governance_agent.py, services/audit_service.py, frontend/App.jsx",
      detail: "Governance blocks unsafe broad deletes and requires exact resource IDs for destructive actions. Audit records approval outcomes. UI pages show filters, charts, row-local execution errors, archive controls, and full theme selection before and after login.",
      output: "User-friendly operational control plane with traceable actions and readable theme choices.",
    },
  ];
  const [activeStep, setActiveStep] = useState(0);
  const selected = workflow[activeStep];

  return (
    <div className="page-stack">
      <div className="architecture-hero">
        <div>
          <h1>Enterprise Architecture</h1>
          <p className="page-subtitle">Interactive workflow for how the React UI, FastAPI routers, LangGraph agents, MCP tools, Azure SDKs, approval queue, and Terraform deployment work together.</p>
        </div>
        <img src={heroImage} alt="" />
      </div>

      <Panel title="Request Workflow">
        <div className="architecture-flow">
          {workflow.map((step, index) => (
            <button
              type="button"
              className={activeStep === index ? "active" : ""}
              key={step.title}
              onClick={() => setActiveStep(index)}
            >
              <span>{String(index + 1).padStart(2, "0")}</span>
              {step.title}
            </button>
          ))}
        </div>
        <div className="architecture-detail">
          <strong>{selected.title}</strong>
          <p>{selected.detail}</p>
          <div className="architecture-facts">
            <span>Actor: {selected.actor}</span>
            <span>Code path: {selected.files}</span>
            <span>UI output: {selected.output}</span>
          </div>
        </div>
      </Panel>

      <div className="architecture-grid">
        {[
          ["Frontend", "React/Vite SPA, Recharts visualizations, live Azure credential headers, ChatOps composer, approval queue, CloudOps filters, security posture, architecture workflow."],
          ["Backend API", "FastAPI routers for Azure connection, cost, cloud resources, forecast, anomalies, approvals, chat, MCP tools, security, alerts, and Teams endpoints."],
          ["Agent Layer", "LangGraph supervisor plus FinOps, CloudOps, Security, Forecast, Anomaly, Advisor, Incident, Governance, Alert, Knowledge, and Remediation agents."],
          ["MCP Tool Layer", "In-process MCP registry with FinOps, CloudOps, Execution, Knowledge, Notification, Monitoring, and Security tools. Execution tools are approval-gated."],
          ["Azure Integrations", "Cost Management, Consumption usageDetails fallback, Resource Graph, Advisor, Monitor Metrics, Resource Health, Policy Insights, Defender securityresources, Web Apps, Compute, Container Apps, Storage, Key Vault, Azure OpenAI."],
          ["Safety Model", "Per-request Azure account binding, exact ARM ID parsing, broad destructive delete blocking, transactional approval execution, retryable pending failures, append-only audit logging."],
          ["Deployment", "Terraform provisions Container Apps, ACR, Key Vault, Log Analytics, App Insights, AI Search, and budgets. Docker images are deployed through ACR when local Docker or ACR Tasks are available."],
        ].map(([title, text], index) => (
          <section className="architecture-layer" key={title}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div>
              <h2>{title}</h2>
              <p>{text}</p>
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function SettingsPage({ connection, disconnect, theme, setTheme }) {
  return (
    <div className="page-stack">
      <div>
        <h1>Connection & Platform</h1>
        <p className="page-subtitle">Connected subscription: {connection.subscriptionId}</p>
      </div>
      <Panel title="Live Connection">
        <div className="settings-card">
          <ShieldCheck size={24} />
          <div>
            <strong>Azure service principal connected</strong>
            <span>Tenant and secret values are hidden in the UI.</span>
          </div>
          <button className="ghost-button" onClick={disconnect}>Disconnect</button>
        </div>
      </Panel>
      <Panel title="API Access">
        <div className="settings-card">
          <ExternalLink size={24} />
          <div>
            <strong>FastAPI documentation</strong>
            <span>Use the API docs link to inspect every live endpoint and MCP route.</span>
          </div>
        </div>
      </Panel>
      <Panel title="Workspace Theme">
        <div className="settings-card">
          <Moon size={24} />
          <div>
            <strong>Choose your workspace theme</strong>
            <span>Select the palette that feels easiest to read. This changes the whole dashboard and is saved on this browser.</span>
          </div>
          <select className="theme-select" value={theme} onChange={(event) => setTheme(event.target.value)}>
            {THEMES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </div>
      </Panel>
    </div>
  );
}

const operationActions = [
  { label: "Stop VM", command: "stop vm", type: "vm" },
  { label: "Start VM", command: "start vm", type: "vm" },
  { label: "Restart VM", command: "restart vm", type: "vm" },
  { label: "Resize VM", command: "resize vm", type: "vm", needsSku: true },
  { label: "Restart App Service", command: "restart app service", type: "app" },
  { label: "Stop App Service", command: "stop app service", type: "app" },
  { label: "Start App Service", command: "start app service", type: "app" },
  { label: "Scale Container App", command: "scale container app", type: "containerapp", needsScale: true },
  { label: "Restore Blob", command: "restore blob", type: "storage", needsBlob: true },
  { label: "Check Blob", command: "check blob", type: "storage", needsBlob: true, readOnly: true },
  { label: "Delete Selected Resource", command: "delete resource", type: "any", destructive: true },
  { label: "Create Resource Group", command: "create resource group", type: "create", needsLocation: true },
  { label: "Create Storage Account", command: "create storage account", type: "create", needsLocation: true, needsSku: true },
];

function resourceTypeBucket(resource) {
  const type = String(resource?.type || "").toLowerCase();
  const rawType = String(resource?.raw_type || "").toLowerCase();
  const combined = `${type} ${rawType}`;
  if (combined.includes("microsoft.compute/virtualmachines") || combined.includes("virtual machine")) return "vm";
  if (combined.includes("microsoft.web/sites") || combined.includes("app service")) return "app";
  if (combined.includes("microsoft.app/containerapps") || combined.includes("container app")) return "containerapp";
  if (combined.includes("microsoft.storage/storageaccounts") || combined.includes("storage account")) return "storage";
  return "other";
}

function supportedResourceActions(resource) {
  const bucket = resourceTypeBucket(resource);
  const base = [];
  if (bucket === "vm") base.push(
    { key: "stop", label: "Stop", command: "stop_vm" },
    { key: "start", label: "Start", command: "start_vm" },
    { key: "restart", label: "Restart", command: "restart_vm" },
    { key: "resize", label: "Resize", command: "resize_vm" },
  );
  if (bucket === "app") base.push(
    { key: "stop", label: "Stop", command: "stop_app_service" },
    { key: "start", label: "Start", command: "start_app_service" },
    { key: "restart", label: "Restart", command: "restart_app_service" },
  );
  if (bucket === "containerapp") base.push(
    { key: "scale", label: "Scale", command: "scale_container_app" },
  );
  if (bucket === "storage") base.push(
    { key: "restore", label: "Restore blob", command: "restore_blob" },
  );
  base.push({ key: "delete", label: "Delete", command: "delete_resource", destructive: true });
  return base;
}

function defaultSpendAction(resource) {
  const actions = supportedResourceActions(resource).filter((item) => ["stop", "scale"].includes(item.key));
  return actions[0] || supportedResourceActions(resource).find((item) => item.key !== "delete") || null;
}

function ChatPanel({ connection, onMutation, resources = [] }) {
  const [open, setOpen] = useState(true);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [operation, setOperation] = useState({ action: "stop vm", resource: "", resourceId: "", group: "", sku: "", min: "1", max: "3", blob: "", filter: "", location: "eastus" });
  const endRef = useRef(null);
  const quickCommands = ["show my azure cost", "list resources", "show advisor recommendations", "show security posture", "list pending approvals"];
  const availableBuckets = useMemo(() => new Set(resources.map(resourceTypeBucket)), [resources]);
  const availableActions = useMemo(() => {
    const liveActions = operationActions.filter((item) => item.type === "create" || item.type === "any" || availableBuckets.has(item.type));
    return liveActions.length ? liveActions : operationActions;
  }, [availableBuckets]);
  const selectedAction = availableActions.find((item) => item.command === operation.action) || availableActions[0] || operationActions[0];
  const resourceOptions = useMemo(() => (
    resources
      .filter((resource) => selectedAction.type === "any" || resourceTypeBucket(resource) === selectedAction.type)
      .map((resource) => ({ resource, score: resourceSearchScore(resource, operation.filter) }))
      .filter((item) => !operation.filter.trim() || item.score >= 18)
      .sort((a, b) => b.score - a.score || String(a.resource.name).localeCompare(String(b.resource.name)))
      .map((item) => item.resource)
  ), [resources, selectedAction.type, operation.filter]);

  useEffect(() => {
    if (!availableActions.some((item) => item.command === operation.action)) {
      setOperation((prev) => ({ ...prev, action: availableActions[0]?.command || "stop vm", resource: "", resourceId: "", group: "", filter: "" }));
    }
  }, [availableActions, operation.action]);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [messages, open]);

  async function send() {
    const message = input.trim();
    if (!message || loading) return;
    const nextMessages = [...messages, { role: "user", content: message }];
    setMessages(nextMessages);
    setInput("");
    setLoading(true);
    try {
      const result = await apiFetch("/chat", connection, {
        method: "POST",
        body: JSON.stringify({ message, history: messages }),
      });
      setMessages((prev) => [...prev, {
        role: "assistant",
        content: result.response,
        agent: result.agent_used,
        approvals: normalizeApprovals(result.actions_proposed),
      }]);
      if (result.actions_proposed?.length || result.tool_results?.some((item) => item.tool === "decide_approval")) {
        onMutation?.();
      }
    } catch (err) {
      setMessages((prev) => [...prev, { role: "assistant", content: err.message, error: true }]);
    } finally {
      setLoading(false);
    }
  }

  function sendText(text) {
    setInput(text);
  }

  async function decideChatApproval(approvalId, decision) {
    const normalizedId = approvalId || "";
    if (!normalizedId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const result = await apiFetch(`/approvals/${normalizedId}/decide`, connection, {
        method: "POST",
        body: JSON.stringify({ decision, approved_by: "chatops", notes: "Decided inline from Azure ChatOps" }),
      });
      const detail = result.execution_result?.error || result.execution_result?.message || result.execution_result?.note || "";
      setMessages((prev) => prev.map((message) => ({
        ...message,
        approvals: (message.approvals || []).filter((approval) => approval.id !== approvalId),
      })).concat({
        role: "assistant",
        agent: "approval_service",
        content: `${approvalId} ${decision}. Execution status: ${result.execution_result?.status || result.status || "recorded"}.${detail ? ` ${detail}` : ""}`,
      }));
      onMutation?.();
    } catch (err) {
      setMessages((prev) => [...prev, { role: "assistant", content: err.message, error: true }]);
    } finally {
      setLoading(false);
    }
  }

  function composeOperation() {
    const resourceName = operation.resource.trim();
    const groupName = operation.group.trim();
    const resourceId = operation.resourceId;
    const exactResource = [
      resourceName,
      groupName ? `in resource group ${groupName}` : "",
      resourceId ? `with exact ARM resource_id ${resourceId}` : "",
    ].filter(Boolean).join(" ");
    const exactSuffix = "Create an approval only for this exact requested operation. Do not substitute delete, stop, restart, resize, scale, or any other action. If the resource is protected by guardrail, do not create approval and explain that protection must be turned off with Azure client ID and secret.";

    if (operation.action === "create resource group") {
      setInput([
        "create resource group",
        resourceName || groupName,
        "region",
        operation.location || "eastus",
        "only if guardrails allow approval creation.",
      ].filter(Boolean).join(" "));
      return;
    }
    if (operation.action === "create storage account") {
      setInput([
        "create storage account",
        resourceName,
        "rg",
        groupName,
        "region",
        operation.location || "eastus",
        operation.sku.trim() ? "sku" : "",
        operation.sku.trim(),
        exactSuffix,
      ].filter(Boolean).join(" "));
      return;
    }
    if (operation.action === "delete resource") {
      const parts = [
        "delete azure resource",
        exactResource,
        groupName ? `rg ${groupName}` : "",
        resourceId ? `resource_id ${resourceId}` : "",
        exactSuffix,
      ];
      setInput(parts.filter(Boolean).join(" "));
      return;
    }
    if (selectedAction.readOnly) {
      const blobName = operation.blob.trim();
      const parts = ["check blob", blobName, "storage_account", resourceName];
      if (groupName) parts.push("rg", groupName);
      setInput(parts.filter(Boolean).join(" "));
      return;
    }
    const parts = [operation.action, selectedAction.needsBlob && operation.blob.trim() ? operation.blob.trim() : resourceName];
    if (selectedAction.needsSku && operation.sku.trim()) {
      parts.push("to", operation.sku.trim());
    }
    if (selectedAction.needsScale) {
      parts.push("min", operation.min || "1", "max", operation.max || "3");
    }
    if (selectedAction.needsBlob && resourceName) {
      parts.push("storage_account", resourceName);
    }
    if (groupName) {
      parts.push("rg", groupName);
    }
    if (resourceId) {
      parts.push("resource_id", resourceId);
    }
    parts.push(exactSuffix);
    setInput(parts.filter(Boolean).join(" "));
  }

  function chooseResource(resourceId) {
    const resource = resources.find((item) => item.id === resourceId || item.name === resourceId);
    if (!resource) return;
    setOperation((prev) => ({
      ...prev,
      resource: resource.name || "",
      resourceId: resource.id || "",
      group: resource.resource_group || resource.resourceGroup || "",
      location: resource.region || prev.location,
    }));
  }

  if (!open) {
    return (
      <button className="chat-launch" onClick={() => setOpen(true)} aria-label="Open chatbot">
        <MessageSquare size={20} />
      </button>
    );
  }

  return (
    <aside className="chat-panel">
      <div className="chat-head">
        <div>
          <strong>Azure ChatOps</strong>
          <span>LangGraph + MCP tools</span>
        </div>
        <button onClick={() => setOpen(false)} aria-label="Close chatbot"><X size={17} /></button>
      </div>
      <div className="chat-body">
        <div className="quick-command-row">
          {quickCommands.map((command) => (
            <button key={command} onClick={() => sendText(command)}>{command}</button>
          ))}
        </div>
        <div className="operation-composer">
          <select value={operation.action} onChange={(e) => setOperation((prev) => ({ ...prev, action: e.target.value }))}>
            {availableActions.map((item) => <option value={item.command} key={item.command}>{item.label}</option>)}
          </select>
          <input
            value={operation.filter}
            onChange={(e) => setOperation((prev) => ({ ...prev, filter: e.target.value }))}
            placeholder={`search ${selectedAction.type} resources`}
          />
          {selectedAction.type !== "create" ? (
            <select value="" onChange={(e) => chooseResource(e.target.value)} title="Pick a live Azure resource">
              <option value="">{resourceOptions.length ? "Pick live resource" : `No ${selectedAction.type} resource`}</option>
              {resourceOptions.map((resource) => (
                <option key={resource.id || `${resource.name}-${resource.resource_group}`} value={resource.id || resource.name}>
                  {resource.name} ({resource.resource_group || "no rg"})
                </option>
              ))}
            </select>
          ) : null}
          <input value={operation.resource} onChange={(e) => setOperation((prev) => ({ ...prev, resource: e.target.value }))} placeholder={selectedAction.type === "create" ? "new resource name" : "resource name"} />
          <input value={operation.group} onChange={(e) => setOperation((prev) => ({ ...prev, group: e.target.value }))} placeholder="resource group" />
          {selectedAction.needsLocation ? (
            <input value={operation.location} onChange={(e) => setOperation((prev) => ({ ...prev, location: e.target.value }))} placeholder="region, for example eastus" />
          ) : null}
          {selectedAction.needsSku ? (
            <input value={operation.sku} onChange={(e) => setOperation((prev) => ({ ...prev, sku: e.target.value }))} placeholder="target SKU" />
          ) : null}
          {selectedAction.needsScale ? (
            <>
              <input value={operation.min} onChange={(e) => setOperation((prev) => ({ ...prev, min: e.target.value }))} placeholder="min replicas" />
              <input value={operation.max} onChange={(e) => setOperation((prev) => ({ ...prev, max: e.target.value }))} placeholder="max replicas" />
            </>
          ) : null}
          {selectedAction.needsBlob ? (
            <input className="wide-field" value={operation.blob} onChange={(e) => setOperation((prev) => ({ ...prev, blob: e.target.value }))} placeholder="blob path, for example assets/logo.png" />
          ) : null}
          <button onClick={composeOperation} type="button"><PlayCircle size={15} /> Compose</button>
        </div>
        {messages.length ? messages.map((message, index) => (
          <div className={`chat-message ${message.role} ${message.error ? "error" : ""}`} key={`${message.role}-${index}`}>
            {message.agent ? <small>{message.agent}</small> : null}
            <p>{message.content}</p>
            {(message.approvals || []).map((approval) => (
              <div className="chat-approval" key={approval.id || approval.approval_id}>
                <div>
                  <strong>{approval.action || approval.action_type}</strong>
                  <span>{approval.id || approval.approval_id} | {approval.risk || "Medium"} risk</span>
                  <small>{approval.resource}</small>
                </div>
                <button className="approve-button" type="button" onClick={() => decideChatApproval(approval.id || approval.approval_id, "approved")} disabled={loading}>
                  <CheckCircle2 size={13} /> Approve
                </button>
                <button className="reject-button" type="button" onClick={() => decideChatApproval(approval.id || approval.approval_id, "rejected")} disabled={loading}>
                  <XCircle size={13} /> Reject
                </button>
              </div>
            ))}
          </div>
        )) : (
          <EmptyState icon={Bot} title="Ask about your Azure account" text="Examples: why did spend increase, list unhealthy resources, propose cost optimizations." />
        )}
        {loading ? <div className="chat-loading"><Loader2 className="spin" size={16} /> Running tools</div> : null}
        <div ref={endRef} />
      </div>
      <div className="chat-input">
        <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder="Ask the Azure operator..." />
        <button onClick={send} disabled={loading || !input.trim()} aria-label="Send message"><Send size={16} /></button>
      </div>
    </aside>
  );
}

const navItems = [
  ["dashboard", "Operations", DollarSign],
  ["cost", "Cost Explorer", IndianRupee],
  ["cloudops", "CloudOps", Server],
  ["security", "Security", ShieldCheck],
  ["forecast", "Forecast", TrendingUp],
  ["anomalies", "Anomalies", AlertTriangle],
  ["approvals", "Approvals", CheckSquare],
  ["architecture", "Architecture", Container],
  ["settings", "Settings", Settings],
];

export default function App() {
  const [connection, setConnection] = useState(loadConnection);
  const [connectionStatus, setConnectionStatus] = useState(null);
  const [page, setPage] = useState("dashboard");
  const [snapshot, setSnapshot] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [theme, setTheme] = useState(loadTheme);

  const connected = useMemo(() => Object.values(connection).every(Boolean), [connection]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  const refresh = useCallback(async () => {
    if (!connected) return;
    setLoading(true);
    setError("");
    try {
      const [cost, resources, recommendations, approvals, security, guardrails] = await Promise.all([
        optionalFetch("/cost/summary", connection, (err) => ({
          mtd_spend: 0,
          budget_monthly: 0,
          budget_utilisation_pct: 0,
          trend: [],
          by_service: {},
          data_source: "error",
          note: err.message,
        })),
        optionalFetch("/cloudops/resources", connection, { total: 0, resources: [], unknown: 0 }),
        optionalFetch("/anomalies/recommendations", connection, { total: 0, recommendations: [] }),
        optionalFetch("/approvals/", connection, { items: [], total: 0 }),
        optionalFetch("/security/posture", connection, (err) => ({
          security: { total: 0, findings: [], data_source: "error", note: err.message },
          policy: { total_non_compliant: 0, items: [], data_source: "error", note: err.message },
        })),
        optionalFetch("/guardrails/", connection, {
          chat_mutations_enabled: true,
          protected_resources: [],
          spend_rules: [],
        }),
      ]);
      let anomalies = {
        total: 0,
        items: [],
        note: (cost.trend || []).length
          ? `Need at least five daily Azure cost points before anomaly detection can run; Azure returned ${(cost.trend || []).length}.`
          : cost.note || "Cost anomaly detection waits for live Azure cost rows.",
      };
      let forecast = {
        horizon_days: 30,
        predictions: [],
        note: cost.note || "Forecast waits for live Azure daily cost rows.",
      };
      if ((cost.trend || []).length > 0) {
        forecast = await apiFetch("/forecast/30d", connection);
      }
      if ((cost.trend || []).length >= 5) {
        anomalies = await apiFetch("/anomalies/", connection);
      }
      setSnapshot({ cost, resources, anomalies, recommendations, forecast, approvals, security, guardrails });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [connected, connection]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
  }, [refresh]);

  function handleConnect(nextConnection, status) {
    setConnection(nextConnection);
    setConnectionStatus(status);
  }

  function disconnect() {
    sessionStorage.removeItem(STORAGE_KEY);
    setConnection(emptyConnection);
    setSnapshot({});
    setConnectionStatus(null);
    setPage("dashboard");
  }

  if (!connected) {
    return <AzureConnect connection={connection} onConnect={handleConnect} theme={theme} setTheme={setTheme} />;
  }

  const Page = {
    dashboard: <Dashboard connection={connection} snapshot={snapshot} loading={loading} error={error} refresh={refresh} />,
    cost: <CostExplorer connection={connection} snapshot={snapshot} />,
    cloudops: <CloudOps snapshot={snapshot} connection={connection} refresh={refresh} />,
    security: <SecurityPage snapshot={snapshot} />,
    forecast: <ForecastPage snapshot={snapshot} />,
    anomalies: <AnomalyPage snapshot={snapshot} />,
    approvals: <ApprovalsPage snapshot={snapshot} connection={connection} refresh={refresh} />,
    architecture: <Architecture />,
    settings: <SettingsPage connection={connection} disconnect={disconnect} theme={theme} setTheme={setTheme} />,
  }[page];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="logo">
          <Zap size={20} />
          <div>
            <strong>FinOps.AI</strong>
            <span>Azure operator | {BUILD_VERSION}</span>
          </div>
        </div>
        <nav>
          {navItems.map(([id, label, Icon]) => (
            <button className={page === id ? "active" : ""} key={id} onClick={() => setPage(id)}>
              <Icon size={17} />
              {label}
            </button>
          ))}
        </nav>
        <div className="sidebar-status">
          <CheckCircle2 size={15} />
          <span>{connectionStatus?.resource_count ?? snapshot.resources?.total ?? 0} Azure resources</span>
        </div>
        <div className="sidebar-theme">
          <span>Theme</span>
          <select value={theme} onChange={(event) => setTheme(event.target.value)} aria-label="Choose color theme">
            {THEMES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </div>
      </aside>
      <main className="content">{Page}</main>
      <ChatPanel connection={connection} onMutation={refresh} resources={snapshot.resources?.resources || []} />
      <a className="docs-link" href={`${API}/docs`} target="_blank" rel="noreferrer">
        <ExternalLink size={15} />
        API docs
      </a>
    </div>
  );
}
