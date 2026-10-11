(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const motionReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const gsap = window.gsap;
  let revealObserver = null;
  const revealSelector = ".section-heading,.metric-card,.panel,.welcome-card,.source-panel,.tab-empty-state,.footer";

  function observeReveals(root = document) {
    if (!revealObserver) return;
    const elements = [];
    if (root instanceof Element && root.matches(revealSelector)) elements.push(root);
    elements.push(...root.querySelectorAll(revealSelector));
    elements.forEach((element) => {
      element.dataset.motionReveal = "";
      if (element.dataset.motionObserved) return;
      element.dataset.motionObserved = "true";
      revealObserver.observe(element);
    });
  }

  function initializeMotion() {
    if (!gsap || motionReduced || !("IntersectionObserver" in window)) return;
    document.documentElement.classList.add("motion-ready");
    revealObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry, index) => {
        if (!entry.isIntersecting) return;
        revealObserver.unobserve(entry.target);
        gsap.fromTo(entry.target,
          { autoAlpha: 0, y: 16 },
          {
            autoAlpha: 1,
            y: 0,
            duration: 0.48,
            delay: Math.min(index * 0.035, 0.14),
            ease: "power2.out",
            clearProps: "opacity,visibility,transform"
          });
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -32px 0px" });
    observeReveals();
  }

  initializeMotion();
  const runButtons = [
    $("#run-analysis"),
    $("#welcome-run"),
    $("#refresh-button"),
    ...document.querySelectorAll("[data-run-analysis]")
  ];
  const fileInput = $("#csv-file");
  const sampleRows = $("#sample-rows");
  const notice = $("#notice");
  let qualityExpanded = false;
  let qualityIssues = [];
  let currentAnalysis = null;
  let statusPollInProgress = false;
  const tabTitles = {
    overview: { title: "Overview", subtitle: "A clear view of your pipeline health, performance, and risks." },
    health: { title: "Task health", subtitle: "Compare run volume, detected failures, and duration by task." },
    risk: { title: "Risk analysis", subtitle: "Review the pipeline runs most likely to become bottlenecks." },
    quality: { title: "Data quality", subtitle: "Validate completeness, formats, schemas, and metric ranges." },
    performance: { title: "Performance", subtitle: "Explore pipeline runtime and resource utilization." },
    monitor: { title: "Monitor & recovery", subtitle: "Review pipeline activity, retries, and recovery outcomes." },
    reports: { title: "Reports", subtitle: "Browse, review, and download saved analysis reports." },
    scheduler: { title: "Scheduler", subtitle: "Configure recurring pipeline reliability analyses." }
  };
  const tabHashes = {
    overview: "#overview",
    health: "#task-health",
    risk: "#risk-analysis",
    quality: "#data-quality",
    performance: "#performance",
    monitor: "#monitoring",
    reports: "#reports",
    scheduler: "#scheduler"
  };
  let activeTab = "overview";

  const hour = new Date().getHours();
  const greetingPeriod = hour >= 5 && hour < 12
    ? "morning"
    : hour < 17 && hour >= 12
      ? "afternoon"
      : hour < 21 && hour >= 17
        ? "evening"
        : "night";
  const greeting = $("#greeting-period");
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    greeting.textContent = greetingPeriod;
  } else {
    greeting.textContent = "";
    greeting.classList.add("is-typing");
    let typedCharacters = 0;
    const typeGreeting = () => {
      typedCharacters += 1;
      greeting.textContent = greetingPeriod.slice(0, typedCharacters);
      if (typedCharacters < greetingPeriod.length) {
        window.setTimeout(typeGreeting, 85);
      } else {
        greeting.classList.remove("is-typing");
      }
    };
    window.setTimeout(typeGreeting, 180);
  }

  const number = (value) => Number(value || 0).toLocaleString();
  const percent = (value, digits = 1) => `${(Number(value || 0) * 100).toFixed(digits)}%`;
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[character]);

  function showNotice(message, title = "We couldn’t complete the analysis") {
    $("#notice-title").textContent = title;
    $("#notice-message").textContent = message;
    notice.hidden = false;
    notice.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function clearNotice() {
    notice.hidden = true;
    $("#notice-message").textContent = "";
  }

  function setSystemStatus(ready, schedule = null) {
    const status = $("#system-status");
    const live = ready && Boolean(schedule?.enabled);
    status.classList.toggle("offline", !ready);
    status.classList.toggle("live", live);
    const label = !ready
      ? "Connection unavailable"
      : live
        ? schedule.running
          ? "Live · analyzing"
          : `Live · every ${number(schedule.interval_seconds)}s`
        : "System ready";
    status.innerHTML = `<span class="status-dot"></span> ${escapeHtml(label)}`;
  }

  function updateLastRun(generatedAt) {
    const timestamp = new Date(generatedAt);
    if (!Number.isNaN(timestamp.getTime())) {
      $("#last-run").textContent = `Updated ${new Intl.DateTimeFormat(undefined, {
        hour: "numeric", minute: "2-digit"
      }).format(timestamp)}`;
    }
  }

  async function refreshLiveState(showError = false) {
    if (statusPollInProgress || document.visibilityState === "hidden") return;
    statusPollInProgress = true;
    try {
      const state = await readResponse(await fetch("/api/status"));
      setSystemStatus(Boolean(state.ready), state.schedule);
      if (state.latest_analysis && !$("#run-analysis").disabled &&
          state.latest_analysis.generated_at !== currentAnalysis?.generated_at) {
        renderResults(state.latest_analysis);
        updateLastRun(state.latest_analysis.generated_at);
      }
    } catch (error) {
      setSystemStatus(false);
      if (showError) {
        showNotice(error instanceof Error ? error.message : "Could not connect to the analysis service.", "Service unavailable");
      }
    } finally {
      statusPollInProgress = false;
    }
  }

  function activateTab(tab, updateHistory = true) {
    if (!Object.hasOwn(tabTitles, tab)) tab = "overview";
    activeTab = tab;

    document.querySelectorAll(".side-nav [data-tab]").forEach((link) => {
      const selected = link.dataset.tab === tab;
      link.classList.toggle("active", selected);
      link.setAttribute("aria-selected", String(selected));
      link.setAttribute("aria-label", link.textContent.trim());
      link.title = link.textContent.trim();
      link.tabIndex = selected ? 0 : -1;
    });
    $(".breadcrumbs strong").textContent = tabTitles[tab].title;
    $(".page-subtitle").textContent = tabTitles[tab].subtitle;
    if (["reports", "scheduler", "monitor"].includes(tab) && $("#results").hidden) {
      $("#results").hidden = false;
    }
    const hasAnalysis = currentAnalysis !== null;
    document.querySelectorAll("[data-tab-view]").forEach((view) => {
      const needsAnalysis = ["overview", "health", "risk", "quality", "performance"].includes(tab);
      view.hidden = view.dataset.tabView !== tab || (!hasAnalysis && needsAnalysis);
    });
    $("#welcome-card").hidden = tab !== "overview" || hasAnalysis;
    $("#health-empty").hidden = tab !== "health" || hasAnalysis;
    $("#risk-empty").hidden = tab !== "risk" || hasAnalysis;
    $("#quality-empty").hidden = tab !== "quality" || hasAnalysis;
    $("#performance-empty").hidden = tab !== "performance" || hasAnalysis;
    $("#monitor-empty").hidden = true;
    const activeView = [...document.querySelectorAll("[data-tab-view],.tab-empty-state,.welcome-card")]
      .find((view) => !view.hidden);
    if (activeView && gsap && !motionReduced) {
      gsap.killTweensOf(activeView);
      gsap.fromTo(activeView,
        { autoAlpha: 0, y: 10 },
        { autoAlpha: 1, y: 0, duration: 0.3, ease: "power2.out", clearProps: "opacity,visibility,transform" });
    }
    observeReveals();

    if (updateHistory && window.location.hash !== tabHashes[tab]) {
      window.history.pushState({ tab }, "", tabHashes[tab]);
    }
    void loadTabData(tab);
  }

  function setBusy(busy) {
    runButtons.forEach((button) => {
      button.disabled = busy;
      button.setAttribute("aria-busy", String(busy));
    });
    $("#loading-panel").hidden = !busy;
    $("#run-analysis").innerHTML = busy
      ? '<span class="loader" aria-hidden="true"></span> Analyzing…'
      : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7V5Z"/></svg> Run analysis';
  }

  async function readResponse(response) {
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new Error("The server returned an unreadable response. Please try again.");
    }
    if (!response.ok) {
      throw new Error(payload.error || `The request failed (${response.status}). Please check your data and try again.`);
    }
    return payload;
  }

  async function runAnalysis() {
    clearNotice();
    setBusy(true);
    const form = new FormData();
    if (fileInput.files && fileInput.files[0]) {
      form.append("file", fileInput.files[0]);
    } else {
      form.append("rows", sampleRows.value || "30000");
    }

    try {
      const response = await fetch("/api/analyze", { method: "POST", body: form });
      renderResults(await readResponse(response));
      setSystemStatus(true);
      $("#last-run").textContent = `Updated ${new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date())}`;
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "An unexpected issue occurred. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  function renderResults(data) {
    currentAnalysis = data;
    const failures = data.failures || {};
    const quality = data.data_quality || {};
    const model = data.model || {};
    const rows = Number(failures.records || data.rows_clean || 0);
    const flagged = Number(failures.total_flagged || 0);
    const reliability = rows ? Math.max(0, 1 - flagged / rows) : 0;
    const issues = Array.isArray(quality.issues) ? quality.issues : [];
    qualityIssues = issues;
    qualityExpanded = false;
    const qualityScore = Math.max(0, Math.round(100 - issues.reduce((sum, issue) => {
      const count = Number(issue.count || 1);
      return sum + (issue.critical ? Math.min(count, 20) * 2 : Math.min(count, 10));
    }, 0)));

    $("#welcome-card").hidden = true;
    $("#results").hidden = false;
    updateLastRun(data.generated_at);
    activateTab(activeTab, false);
    $("#source-badge").textContent = data.source || "Analysis complete";
    $("#result-summary").textContent = `${number(data.rows_raw)} records reviewed · ${number(data.rows_clean)} passed cleaning`;
    $("#reliability-value").textContent = percent(reliability);
    $("#reliability-foot").textContent = `${number(flagged)} run${flagged === 1 ? "" : "s"} flagged for review`;
    $("#reliability-meter").style.width = `${Math.round(reliability * 100)}%`;
    $("#runs-value").textContent = number(data.rows_clean);
    $("#runs-foot").textContent = "Clean records analyzed";
    $("#raw-records").textContent = `${number(data.rows_raw)} records received`;
    $("#flagged-value").textContent = number(flagged);
    $("#flagged-foot").textContent = `${number(failures.rule_flagged)} rule-based · ${number(failures.anomaly_flagged)} anomaly`;
    $("#flagged-rate").textContent = `${percent(rows ? flagged / rows : 0, 2)} of analyzed runs`;
    $("#model-value").textContent = model.f1 == null ? "N/A" : percent(model.f1);
    $("#model-foot").textContent = `${number(model.train_rows)} training · ${number(model.test_rows)} test`;
    $("#quality-percent").textContent = `${qualityScore}%`;
    $("#quality-ring").style.background = `conic-gradient(${quality.critical_failure ? "#e2696e" : "#34b88c"} ${qualityScore}%,#edf1f4 ${qualityScore}%)`;
    $("#quality-status").textContent = quality.critical_failure ? "Needs attention" : issues.length ? "Review suggested" : "Looking good";
    $("#quality-detail").textContent = `${issues.length} check${issues.length === 1 ? "" : "s"} with findings · ${number(quality.rows)} input rows`;

    renderQuality(issues);
    renderTimeline(Array.isArray(data.timeline) ? data.timeline : []);
    renderTasks(Array.isArray(data.by_task) ? data.by_task : []);
    renderRisks(Array.isArray(data.top_risk) ? data.top_risk : []);
    renderDetailedQuality(data);
    renderPerformance(data);
    observeReveals();
    observeReveals();
    if (activeTab === "monitor") void loadTabData("monitor");
    if (activeTab === "reports") void loadTabData("reports");
    if (activeTab === "scheduler") void loadTabData("scheduler");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function qualityLabel(issue) {
    const labels = {
      schema_missing_columns: `Missing columns: ${(issue.columns || []).join(", ")}`,
      invalid_dtype: `Invalid type · ${issue.column || "column"}`,
      missing_values: `Missing values · ${issue.column || "column"}`,
      duplicate_rows: "Duplicate rows",
      negative_values: `Negative values · ${issue.column || "column"}`,
      range_violation: `Out of range · ${issue.column || "column"}`
    };
    return labels[issue.type] || String(issue.type || "Data check").replaceAll("_", " ");
  }

  function renderQuality(issues) {
    const visible = qualityExpanded ? issues : issues.slice(0, 4);
    const items = visible.map((issue) => {
      const count = issue.count == null ? ((issue.columns || []).length || "Review") : number(issue.count);
      return `<div class="quality-item"><span>${escapeHtml(qualityLabel(issue))}</span><span>${escapeHtml(count)}</span></div>`;
    });
    if (!issues.length) {
      items.push('<div class="quality-item"><span>Schema and required fields</span><span class="quality-clear">Passed</span></div>');
      items.push('<div class="quality-item"><span>Missing and duplicate data</span><span class="quality-clear">Passed</span></div>');
    }
    $("#quality-list").innerHTML = items.join("");
    const toggle = $("#quality-toggle");
    toggle.hidden = issues.length <= 4;
    toggle.textContent = qualityExpanded ? "Show fewer checks ↑" : `View all ${issues.length} quality checks →`;
  }

  function renderTimeline(points, selector = "#timeline-chart") {
    const target = $(selector);
    if (!points.length) {
      target.innerHTML = '<div class="empty-chart">No timeline data is available for this analysis.</div>';
      return;
    }
    const width = 720;
    const height = 190;
    const padding = { top: 10, right: 12, bottom: 27, left: 35 };
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;
    const maxDuration = Math.max(...points.map((point) => Number(point.avg_duration) || 0), 1);
    const maxFailures = Math.max(...points.map((point) => Number(point.failures) || 0), 1);
    const grid = [0, 1, 2, 3].map((step) => {
      const y = padding.top + (chartHeight * step / 3);
      return `<line class="chart-grid-line" x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}"></line>`;
    }).join("");
    const bars = points.map((point, index) => {
      const slot = chartWidth / points.length;
      const barHeight = (Number(point.failures || 0) / maxFailures) * chartHeight * 0.55;
      return `<rect class="chart-bar" x="${(padding.left + index * slot + slot * .25).toFixed(1)}" y="${(padding.top + chartHeight - barHeight).toFixed(1)}" width="${Math.max(1, slot * .5).toFixed(1)}" height="${barHeight.toFixed(1)}" rx="2"></rect>`;
    }).join("");
    const coordinates = points.map((point, index) => ({
      x: padding.left + (points.length === 1 ? chartWidth / 2 : index * chartWidth / (points.length - 1)),
      y: padding.top + chartHeight - ((Number(point.avg_duration) || 0) / maxDuration) * chartHeight * .84
    }));
    const path = coordinates.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
    const areaPath = `${path} L${coordinates[coordinates.length - 1].x.toFixed(1)},${(padding.top + chartHeight).toFixed(1)} L${coordinates[0].x.toFixed(1)},${(padding.top + chartHeight).toFixed(1)} Z`;
    const labels = [points[0], points[Math.floor((points.length - 1) / 2)], points[points.length - 1]]
      .filter((point, index, items) => items.indexOf(point) === index)
      .map((point, index, items) => {
        const x = items.length === 1 ? width / 2 : padding.left + index * chartWidth / (items.length - 1);
        return `<text class="chart-label" x="${x}" y="${height - 5}" text-anchor="${index === 0 ? "start" : index === items.length - 1 ? "end" : "middle"}">${escapeHtml(point.t || "")}</text>`;
      }).join("");
    target.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Timeline of average duration and detected failures">
      <defs><linearGradient id="chartFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#6b83f2" stop-opacity=".18"/><stop offset="100%" stop-color="#6b83f2" stop-opacity="0"/></linearGradient></defs>
      ${grid}${bars}<path class="chart-area" d="${areaPath}"></path><path class="chart-line" d="${path}"></path>
      ${coordinates.filter((_, index) => index === 0 || index === coordinates.length - 1 || index % Math.max(1, Math.floor(coordinates.length / 8)) === 0).map((point) => `<circle class="chart-point" cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="3"></circle>`).join("")}
      ${labels}</svg>`;
  }

  function renderTasks(tasks) {
    $("#task-count").textContent = `${number(tasks.length)} tasks`;
    if (!tasks.length) {
      $("#task-rows").innerHTML = '<tr><td colspan="5" class="empty-row">No task-level results are available.</td></tr>';
      return;
    }
    $("#task-rows").innerHTML = tasks.slice().sort((a, b) => Number(b.flagged || 0) - Number(a.flagged || 0)).map((task) => {
      const flagged = Number(task.flagged || 0);
      const rate = Number(task.runs || 0) ? flagged / Number(task.runs) : 0;
      const health = rate > .15 ? "critical" : rate > .05 ? "watch" : "good";
      const label = health === "critical" ? "At risk" : health === "watch" ? "Monitor" : "Healthy";
      return `<tr><td>${escapeHtml(task.task)}</td><td>${number(task.runs)}</td><td>${number(flagged)}</td><td>${Number(task.avg_duration || 0).toFixed(1)}s</td><td><span class="health-pill ${health}">${label}</span></td></tr>`;
    }).join("");
  }

  function renderRisks(risks) {
    if (!risks.length) {
      $("#risk-list").innerHTML = '<div class="empty-row">No bottleneck predictions are available.</div>';
      return;
    }
    $("#risk-list").innerHTML = risks.map((risk) => {
      const score = Math.max(0, Math.min(1, Number(risk.risk || 0)));
      const low = score < .35;
      return `<div class="risk-item ${low ? "low" : ""}">
        <div><div class="risk-task">${escapeHtml(risk.task)}</div><div class="risk-meta">${escapeHtml(String(risk.timestamp || "").slice(0, 16))} · ${Number(risk.duration || 0).toFixed(1)}s</div></div>
        <span class="risk-score">${percent(score)}</span>
        <div class="risk-track"><span style="width:${Math.round(score * 100)}%"></span></div>
      </div>`;
    }).join("");
  }

  function renderDetailedQuality(data) {
    const quality = data.data_quality || {};
    const issues = Array.isArray(quality.issues) ? quality.issues : [];
    const critical = issues.filter((issue) => issue.critical).length;
    const cards = [
      { label: "Rows inspected", value: number(quality.rows) },
      { label: "Checks with findings", value: number(issues.length) },
      { label: "Critical findings", value: number(critical) },
      { label: "Validation state", value: quality.passed ? "Passed" : "Review" }
    ];
    $("#quality-summary-cards").innerHTML = cards.map((card) =>
      `<article class="metric-card"><div class="metric-top">${escapeHtml(card.label)}</div><div class="metric-value">${escapeHtml(card.value)}</div></article>`
    ).join("");
    $("#quality-findings-caption").textContent = issues.length
      ? `${number(issues.length)} validation finding${issues.length === 1 ? "" : "s"} from ${number(quality.rows)} input rows.`
      : "All configured schema, completeness, and range checks passed.";
    $("#quality-findings").innerHTML = issues.length ? issues.map((issue) => {
      const details = [
        issue.expected && `expected ${issue.expected}`,
        issue.found && `found ${issue.found}`,
        issue.minimum != null && `minimum ${issue.minimum}`,
        issue.maximum != null && `maximum ${issue.maximum}`
      ].filter(Boolean).join(" · ");
      return `<div class="quality-finding">
        <span class="finding-marker ${issue.critical ? "critical" : ""}">${issue.critical ? "!" : "i"}</span>
        <div class="finding-copy"><strong>${escapeHtml(qualityLabel(issue))}</strong><span>${escapeHtml(details || (issue.columns || []).join(", ") || "Validation check")}</span></div>
        <span class="finding-count">${issue.count == null ? "Review" : `${number(issue.count)} rows`}</span>
      </div>`;
    }).join("") : '<div class="empty-row">No quality issues found. This dataset passed the configured validation checks.</div>';
  }

  function renderPerformance(data) {
    const metrics = data.performance || {};
    const cards = [
      ["Average duration", `${Number(metrics.avg_duration || 0).toFixed(2)} s`],
      ["95th percentile", `${Number(metrics.p95_duration || 0).toFixed(2)} s`],
      ["Longest run", `${Number(metrics.max_duration || 0).toFixed(2)} s`],
      ["Average CPU", `${Number(metrics.avg_cpu || 0).toFixed(1)}%`],
      ["Average memory", `${Number(metrics.avg_memory || 0).toFixed(1)}%`],
      ["Average I/O", `${Number(metrics.avg_io || 0).toFixed(1)} units`],
      ["Average latency", `${Number(metrics.avg_latency || 0).toFixed(1)} ms`],
      ["Tasks observed", number(metrics.task_count)]
    ];
    $("#performance-metrics").innerHTML = cards.map(([label, value]) =>
      `<article class="metric-card"><div class="metric-top">${escapeHtml(label)}</div><div class="metric-value">${escapeHtml(value)}</div></article>`
    ).join("");
    renderTimeline(Array.isArray(data.timeline) ? data.timeline : [], "#performance-chart");
  }

  async function loadTabData(tab) {
    try {
      if (tab === "quality" && currentAnalysis) {
        renderDetailedQuality(currentAnalysis);
      } else if (tab === "performance" && currentAnalysis) {
        renderPerformance(currentAnalysis);
      } else if (tab === "reports") {
        const [reportData, historyData] = await Promise.all([
          readResponse(await fetch("/api/reports")),
          readResponse(await fetch("/api/history"))
        ]);
        renderReports(reportData.reports || []);
        renderHistory(historyData.history || []);
      } else if (tab === "monitor") {
        const [monitorData, logData] = await Promise.all([
          readResponse(await fetch("/api/monitor")),
          readResponse(await fetch("/api/logs?limit=150"))
        ]);
        renderMonitor(monitorData, logData.logs || []);
      } else if (tab === "scheduler") {
        const [scheduleData, datasetData] = await Promise.all([
          readResponse(await fetch("/api/schedule")),
          readResponse(await fetch("/api/schedule/datasets"))
        ]);
        renderScheduleDatasets(datasetData.datasets || [], scheduleData.schedule.dataset_name);
        renderSchedule(scheduleData.schedule);
      }
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "Could not load this workspace.", "Workspace unavailable");
    }
  }

  function renderReports(reports) {
    $("#reports-count").textContent = `${number(reports.length)} saved report files`;
    $("#report-list").innerHTML = reports.length ? reports.map((report) => {
      const modified = report.modified ? new Date(report.modified).toLocaleString() : "Saved report";
      return `<a class="report-item" href="/api/reports/${encodeURIComponent(report.filename)}" download>
        <span class="report-icon">${report.format === "JSON" ? "{}" : "MD"}</span>
        <span class="report-copy"><strong>${escapeHtml(report.filename)}</strong><span>${escapeHtml(modified)} · ${number(report.size)} bytes</span></span>
        <span class="report-download" aria-hidden="true">↓</span>
      </a>`;
    }).join("") : '<div class="empty-row">No reports yet. Run an analysis to generate JSON and Markdown reports.</div>';
  }

  function renderHistory(items) {
    $("#history-rows").innerHTML = items.length ? items.map((item) => `
      <tr><td>${escapeHtml(new Date(item.generated_at).toLocaleString())}</td>
      <td>${escapeHtml(item.source)}</td><td>${number(item.rows_clean)}</td>
      <td>${number(item.flagged)}</td><td>${Number(item.reliability || 0).toFixed(1)}%</td></tr>`
    ).join("") : '<tr><td colspan="5" class="empty-row">No analysis runs in this server session yet.</td></tr>';
  }

  function renderMonitor(data, logs) {
    const recovery = data.recovery || {};
    const summary = recovery.monitor || {};
    const recoveryStats = recovery.recovery || {};
    const cards = [
      ["Recent analyses", number((data.history || []).length)],
      ["Task attempts", number(summary.total_runs || 0)],
      ["Successful attempts", number(summary.success || 0)],
      ["Tasks recovered", number(recoveryStats.recovered || 0)]
    ];
    $("#monitor-summary").innerHTML = cards.map(([label, value]) =>
      `<article class="metric-card"><div class="metric-top">${escapeHtml(label)}</div><div class="metric-value">${escapeHtml(value)}</div></article>`
    ).join("");
    const records = Array.isArray(recovery.records) ? recovery.records : [];
    $("#monitor-events").innerHTML = records.length ? records.map((record) => {
      const successfulRetry = record.status !== "SUCCESS" && records.find((later) =>
        later.task === record.task
        && later.status === "SUCCESS"
        && Number(later.attempt) > Number(record.attempt)
      );
      const status = successfulRetry
        ? "RETRIED"
        : record.status === "FAILED"
          ? "FAILED"
          : record.status;
      const statusClass = successfulRetry || status === "SUCCESS"
        ? "good"
        : status === "TIMEOUT"
          ? "critical"
          : "watch";
      const details = successfulRetry
        ? `Recovered on attempt ${number(successfulRetry.attempt)} · ${
          record.error_type === "FileNotFoundError"
            ? "temporary source issue"
            : record.error_type === "ConnectionError"
              ? "temporary connection issue"
              : "temporary issue"
        }`
        : record.error_msg || "—";
      return `<tr><td>${escapeHtml(record.task)}</td>
      <td><span class="health-pill ${statusClass}">${escapeHtml(status)}</span></td>
      <td>${number(record.attempt)}</td><td>${Number(record.duration_s || 0).toFixed(3)}s</td>
      <td>${escapeHtml(details)}</td></tr>`;
    }).join("") : '<tr><td colspan="5" class="empty-row">No recovery events recorded. Run the recovery demo to exercise automated retries.</td></tr>';
    const logEntries = [];
    let entry = [];
    const appendEntry = () => {
      if (!entry.length) return;
      const isRecoveryDemo = entry.some((line) =>
        /\|\s(?:monitor|recovery)\s\|\stask=(?:extract|transform|load|validate_schema)\b/.test(line)
        || /applying corrective action '(?:recreate_file|reconnect)'/.test(line)
        || /(?:source file missing|warehouse unreachable|schema mismatch: column 'amount' missing)/.test(line)
      );
      if (!isRecoveryDemo) logEntries.push(...entry);
      entry = [];
    };
    logs.forEach((line) => {
      if (/^(?:\d{4}-\d{2}-\d{2}[ T]|Traceback \(most recent call last\):)/.test(line)) appendEntry();
      entry.push(line);
    });
    appendEntry();
    $("#monitor-logs").textContent = logEntries.length
      ? logEntries.join("\n")
      : "No non-demo execution log entries yet. Recovery-demo attempts are summarized above.";
  }

  function renderSchedule(schedule) {
    $("#schedule-enabled").checked = Boolean(schedule.enabled);
    $("#schedule-interval").value = String(schedule.interval_seconds || 3600);
    const rowsSelect = $("#schedule-rows");
    rowsSelect.value = String(schedule.rows || 10000);
    $("#schedule-source").value = schedule.source_type || "sample";
    $("#schedule-dataset").value = schedule.dataset_name || "";
    syncScheduleSourceControls();
    $("#schedule-state").textContent = schedule.running
      ? "Pipeline analysis running"
      : schedule.enabled ? "Scheduler active" : "Scheduler paused";
    $("#schedule-detail").textContent = schedule.running
      ? "A scheduled data analysis is in progress."
      : schedule.enabled ? "The next run is scheduled below." : "Configure and enable an interval to start automatic runs.";
    $("#schedule-indicator").classList.toggle("enabled", Boolean(schedule.enabled));
    const nextRun = schedule.next_run ? new Date(schedule.next_run).toLocaleString() : "Not scheduled";
    const lastRun = schedule.last_run ? new Date(schedule.last_run).toLocaleString() : "No runs yet";
    $("#schedule-meta").textContent = `Next run: ${nextRun} · Last run: ${lastRun} · Completed runs: ${number(schedule.runs || 0)}`;
    $("#schedule-error").hidden = !schedule.last_error;
    $("#schedule-error").textContent = schedule.last_error || "";
  }

  function renderScheduleDatasets(datasets, selectedName = "") {
    const select = $("#schedule-dataset");
    select.innerHTML = '<option value="">Upload or select a CSV</option>' + datasets.map((dataset) =>
      `<option value="${escapeHtml(dataset.name)}">${escapeHtml(dataset.name)} · ${number(dataset.size)} bytes</option>`
    ).join("");
    if (datasets.some((dataset) => dataset.name === selectedName)) {
      select.value = selectedName;
    }
  }

  function syncScheduleSourceControls() {
    const usesCsv = $("#schedule-source").value === "csv";
    $("#schedule-dataset-field").hidden = !usesCsv;
    $("#schedule-rows-field").hidden = usesCsv;
  }

  async function uploadScheduleCsv() {
    clearNotice();
    const file = $("#schedule-csv-file").files?.[0];
    if (!file) {
      showNotice("Choose an ETL CSV file first.", "No CSV selected");
      return;
    }
    const button = $("#upload-schedule-csv");
    const status = $("#schedule-upload-status");
    button.disabled = true;
    button.textContent = "Saving CSV…";
    status.textContent = "";
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch("/api/schedule/datasets", { method: "POST", body: form });
      const data = await readResponse(response);
      const datasets = await readResponse(await fetch("/api/schedule/datasets"));
      renderScheduleDatasets(datasets.datasets || [], data.dataset.name);
      $("#schedule-source").value = "csv";
      syncScheduleSourceControls();
      status.textContent = `${data.dataset.name} saved and ready for scheduled analysis.`;
      $("#schedule-csv-file").value = "";
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "Could not save the scheduled CSV.", "CSV not saved");
    } finally {
      button.disabled = false;
      button.textContent = "Save CSV for scheduling";
    }
  }

  async function runRecoveryDemo() {
    clearNotice();
    const button = document.activeElement?.closest("#recovery-button, #monitor-recovery-button") || $("#recovery-button");
    const result = $("#recovery-result");
    button.disabled = true;
    button.textContent = "Running demo…";
    result.hidden = true;
    try {
      const response = await fetch("/api/recovery-demo", { method: "POST" });
      const data = await readResponse(response);
      const recovery = data.recovery || {};
      result.textContent = `Recovery demo complete · ${number(data.rows_loaded)} rows loaded · ${number(recovery.recovered || 0)} tasks recovered on retry · ${number(recovery.non_recoverable || 0)} issue${Number(recovery.non_recoverable || 0) === 1 ? "" : "s"} escalated as expected.`;
      result.hidden = false;
      if (activeTab === "monitor") await loadTabData("monitor");
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "The recovery demo couldn’t be completed.");
    } finally {
      button.disabled = false;
      button.innerHTML = 'Run recovery demo <span aria-hidden="true">→</span>';
    }
  }

  runButtons.forEach((button) => button.addEventListener("click", runAnalysis));
  $("#schedule-source").addEventListener("change", syncScheduleSourceControls);
  $("#upload-schedule-csv").addEventListener("click", uploadScheduleCsv);
  $("#recovery-button").addEventListener("click", runRecoveryDemo);
  $("#monitor-recovery-button").addEventListener("click", runRecoveryDemo);
  document.querySelectorAll(".side-nav [data-tab]").forEach((link) => link.addEventListener("click", (event) => {
    event.preventDefault();
    activateTab(link.dataset.tab);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }));
  document.querySelector(".side-nav").addEventListener("keydown", (event) => {
    const links = [...document.querySelectorAll(".side-nav [data-tab]")];
    const currentIndex = links.indexOf(document.activeElement);
    if (currentIndex < 0) return;
    let nextIndex = currentIndex;
    if (event.key === "ArrowDown" || event.key === "ArrowRight") nextIndex += 1;
    else if (event.key === "ArrowUp" || event.key === "ArrowLeft") nextIndex -= 1;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = links.length - 1;
    else return;
    event.preventDefault();
    const nextLink = links[(nextIndex + links.length) % links.length];
    nextLink.focus();
    activateTab(nextLink.dataset.tab);
  });
  window.addEventListener("popstate", () => {
    const hash = window.location.hash;
    const tab = Object.keys(tabHashes).find((name) => tabHashes[name] === hash) || "overview";
    activateTab(tab, false);
  });
  $("#refresh-reports").addEventListener("click", () => void loadTabData("reports"));
  $("#schedule-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    clearNotice();
    const button = $("#save-schedule");
    button.disabled = true;
    button.textContent = "Saving…";
    try {
      const response = await fetch("/api/schedule", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: $("#schedule-enabled").checked,
          interval_seconds: $("#schedule-interval").value,
          rows: $("#schedule-rows").value,
          source_type: $("#schedule-source").value,
          dataset_name: $("#schedule-dataset").value
        })
      });
      const data = await readResponse(response);
      renderSchedule(data.schedule);
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "Could not save the schedule.", "Schedule not saved");
    } finally {
      button.disabled = false;
      button.textContent = "Save schedule";
    }
  });
  const initialTab = Object.keys(tabHashes).find((name) => tabHashes[name] === window.location.hash) || "overview";
  activateTab(initialTab, false);
  void refreshLiveState(true);
  window.setInterval(() => void refreshLiveState(), 2000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void refreshLiveState();
  });
  $(".footer a").addEventListener("click", (event) => {
    event.preventDefault();
    $("#data-source").scrollIntoView({ behavior: "smooth", block: "center" });
  });
  $("#notice-close").addEventListener("click", clearNotice);
  $("#quality-toggle").addEventListener("click", () => {
    qualityExpanded = !qualityExpanded;
    renderQuality(qualityIssues);
  });
  fileInput.addEventListener("change", () => {
    const file = fileInput.files && fileInput.files[0];
    $("#file-label").textContent = file ? file.name : "Choose CSV";
    $("#source-note").textContent = file
      ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`
      : "CSV uploads support 500,000+ rows (up to 500 MB) and need timestamp, task_id, status, duration, cpu_usage, memory_usage, io_throughput, and latency.";
  });

})();
