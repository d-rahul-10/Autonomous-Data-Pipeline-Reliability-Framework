(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const csrfHeaders = () => ({
    "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]')?.content || ""
  });
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
  let currentTaskRows = [];
  let statusPollInProgress = false;
  const tabTitles = {
    overview: { title: "Overview", subtitle: "Health, performance, and risks." },
    health: { title: "Task health", subtitle: "Runs, failures, and runtime." },
    risk: { title: "Risks", subtitle: "Runs needing review." },
    quality: { title: "Data quality", subtitle: "Schema and data checks." },
    performance: { title: "Performance", subtitle: "Runtime and resource use." },
    monitor: { title: "Monitor & recovery", subtitle: "Activity and retries." },
    reports: { title: "Reports", subtitle: "Saved analyses and history." },
    scheduler: { title: "Scheduler", subtitle: "Schedule recurring analyses." }
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
    if (!(fileInput.files && fileInput.files[0]) && !sampleRows.value) {
      showNotice("Upload your ETL CSV or choose a generated sample before running the analysis.", "Choose a data source");
      return;
    }
    setBusy(true);
    const form = new FormData();
    if (fileInput.files && fileInput.files[0]) {
      form.append("file", fileInput.files[0]);
    } else {
      form.append("rows", sampleRows.value);
    }

    try {
      const response = await fetch("/api/analyze", { method: "POST", headers: csrfHeaders(), body: form });
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
    renderRisks(Array.isArray(data.top_risk) ? data.top_risk : [], Array.isArray(data.by_task) ? data.by_task : []);
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
    const chartPoints = points.length > 32
      ? Array.from({ length: 32 }, (_, index) => points[Math.round(index * (points.length - 1) / 31)])
      : points;
    const width = 900;
    const height = 250;
    const padding = { top: 27, right: 52, bottom: 39, left: 58 };
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;
    const maxDuration = Math.max(...chartPoints.map((point) => Number(point.avg_duration) || 0), 1);
    const maxFailures = Math.max(...chartPoints.map((point) => Number(point.failures) || 0), 1);
    const grid = [0, 1, 2, 3].map((step) => {
      const y = padding.top + (chartHeight * step / 3);
      const durationTick = (maxDuration * (1 - step / 3)).toFixed(maxDuration < 10 ? 1 : 0);
      const failureTick = Math.round(maxFailures * (1 - step / 3));
      return `<line class="chart-grid-line" x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}"></line>
        <text class="chart-axis-label" x="${padding.left - 10}" y="${y + 4}" text-anchor="end">${durationTick}</text>
        <text class="chart-axis-label" x="${width - padding.right + 10}" y="${y + 4}" text-anchor="start">${failureTick}</text>`;
    }).join("");
    const bars = chartPoints.map((point, index) => {
      const slot = chartWidth / chartPoints.length;
      const failures = Number(point.failures) || 0;
      const barHeight = (failures / maxFailures) * chartHeight;
      const x = chartPoints.length === 1
        ? padding.left + (chartWidth - Math.max(3, chartWidth * .35)) / 2
        : padding.left + index * slot + slot * .25;
      const barWidth = chartPoints.length === 1 ? Math.max(3, chartWidth * .35) : Math.max(2, slot * .58);
      return `<rect class="chart-bar" x="${x.toFixed(1)}" y="${(padding.top + chartHeight - barHeight).toFixed(1)}" width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}" rx="3"><title>${escapeHtml(point.t || "Run group")} · ${failures} failures</title></rect>`;
    }).join("");
    const coordinates = chartPoints.map((point, index) => ({
      x: padding.left + (chartPoints.length === 1 ? chartWidth / 2 : index * chartWidth / (chartPoints.length - 1)),
      y: padding.top + chartHeight - ((Number(point.avg_duration) || 0) / maxDuration) * chartHeight
    }));
    const path = coordinates.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
    const areaPath = `${path} L${coordinates[coordinates.length - 1].x.toFixed(1)},${(padding.top + chartHeight).toFixed(1)} L${coordinates[0].x.toFixed(1)},${(padding.top + chartHeight).toFixed(1)} Z`;
    const labelIndexes = [...new Set([0, Math.round((chartPoints.length - 1) * .25), Math.round((chartPoints.length - 1) * .5), Math.round((chartPoints.length - 1) * .75), chartPoints.length - 1])];
    const dateLabel = (value) => {
      const parsed = new Date(value);
      return Number.isNaN(parsed.getTime()) ? String(value || "").slice(0, 10)
        : new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(parsed);
    };
    const labels = labelIndexes.map((index) => chartPoints[index])
      .filter((point, index, items) => items.indexOf(point) === index)
      .map((point, index, items) => {
        const sourceIndex = chartPoints.indexOf(point);
        const x = padding.left + (chartPoints.length === 1 ? chartWidth / 2 : sourceIndex * chartWidth / (chartPoints.length - 1));
        return `<text class="chart-label" x="${x}" y="${height - 9}" text-anchor="${index === 0 ? "start" : index === items.length - 1 ? "end" : "middle"}"><title>${escapeHtml(point.t || "")}</title>${escapeHtml(dateLabel(point.t))}</text>`;
      }).join("");
    const markerIndexes = new Set(Array.from({ length: Math.min(8, chartPoints.length) }, (_, index) => Math.round(index * (chartPoints.length - 1) / Math.max(1, Math.min(8, chartPoints.length) - 1))));
    const markers = coordinates.filter((_, index) => markerIndexes.has(index))
      .map((point) => {
        const item = chartPoints[coordinates.indexOf(point)];
        return `<circle class="chart-point" cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="4"><title>${escapeHtml(item.t || "Run group")} · ${Number(item.avg_duration || 0).toFixed(2)}s average · ${Number(item.failures || 0)} failures</title></circle>`;
      }).join("");
    const gradientId = selector === "#performance-chart" ? "performanceChartFill" : "timelineChartFill";
    target.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Timeline of average duration and detected failures">
      <defs><linearGradient id="${gradientId}" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#60e8df" stop-opacity=".24"/><stop offset="100%" stop-color="#60e8df" stop-opacity="0"/></linearGradient></defs>
      <text class="chart-axis-title" x="${padding.left}" y="13">AVG RUNTIME · SECONDS</text><text class="chart-axis-title" x="${width - padding.right}" y="13" text-anchor="end">FLAGGED RUNS</text>
      ${grid}${bars}<path class="chart-area" d="${areaPath}" style="fill:url(#${gradientId})"></path><path class="chart-line" d="${path}"></path>
      ${markers}
      ${labels}</svg>`;
  }

  function renderTasks(tasks) {
    currentTaskRows = Array.isArray(tasks) ? tasks.slice() : [];
    const totalRuns = currentTaskRows.reduce((sum, task) => sum + Number(task.runs || 0), 0);
    const totalFlagged = currentTaskRows.reduce((sum, task) => sum + Number(task.flagged || 0), 0);
    const worstTask = currentTaskRows.reduce((worst, task) => {
      const rate = Number(task.runs || 0) ? Number(task.flagged || 0) / Number(task.runs) : 0;
      return !worst || rate > worst.rate ? { name: task.task, rate } : worst;
    }, null);
    const taskCount = $("#task-count");
    if (taskCount) taskCount.textContent = `${number(currentTaskRows.length)} tasks`;
    const taskSummary = $("#task-summary");
    if (taskSummary) taskSummary.innerHTML = [
      ["Tasks observed", number(currentTaskRows.length), "Distinct pipeline task IDs"],
      ["Runs reviewed", number(totalRuns), "Across all observed tasks"],
      ["Flagged runs", `${number(totalFlagged)} · ${percent(totalRuns ? totalFlagged / totalRuns : 0)}`, "Runs requiring review"],
      ["Highest task rate", worstTask ? `${percent(worstTask.rate)} · ${escapeHtml(worstTask.name)}` : "N/A", "Flagged share in this dataset"]
    ].map(([label, value, caption]) => `<article class="metric-card task-stat-card"><div class="metric-top">${label}</div><div class="metric-value">${value}</div><div class="subtle-caption">${caption}</div></article>`).join("");

    const topTasks = currentTaskRows.map((task) => ({ ...task, rate: Number(task.runs || 0) ? Number(task.flagged || 0) / Number(task.runs) : 0 }))
      .sort((a, b) => b.rate - a.rate).slice(0, 7);
    const maxRate = Math.max(...topTasks.map((task) => task.rate), .01);
    const taskRateChart = $("#task-rate-chart");
    if (taskRateChart) taskRateChart.innerHTML = topTasks.map((task) => {
      const health = task.rate > .15 ? "critical" : task.rate > .05 ? "watch" : "good";
      return `<div class="task-rate-row"><span class="task-rate-name" title="${escapeHtml(task.task)}">${escapeHtml(task.task)}</span><span class="task-rate-track"><i class="${health}" style="width:${Math.max(task.rate ? 2 : 0, task.rate / maxRate * 100)}%"></i></span><strong>${percent(task.rate)}</strong><small>${number(task.flagged)} / ${number(task.runs)} flagged</small></div>`;
    }).join("") || '<div class="empty-row">Task-level results will appear after analysis.</div>';
    updateTaskTable();
  }

  function updateTaskTable() {
    const taskRows = $("#task-rows");
    if (!taskRows) return;
    const query = $("#task-search")?.value.trim().toLowerCase() || "";
    const sort = $("#task-sort")?.value || "rate";
    const rows = currentTaskRows.filter((task) => String(task.task).toLowerCase().includes(query));
    rows.sort((a, b) => {
      const rateA = Number(a.runs || 0) ? Number(a.flagged || 0) / Number(a.runs) : 0;
      const rateB = Number(b.runs || 0) ? Number(b.flagged || 0) / Number(b.runs) : 0;
      if (sort === "name") return String(a.task).localeCompare(String(b.task));
      const field = { rate: null, flagged: "flagged", duration: "avg_duration", runs: "runs" }[sort] || "flagged";
      const valueA = sort === "rate" ? rateA : Number(a[field] || 0);
      const valueB = sort === "rate" ? rateB : Number(b[field] || 0);
      return valueB - valueA;
    });
    const visibleCount = $("#task-visible-count");
    if (visibleCount) visibleCount.textContent = `${number(rows.length)} shown`;
    taskRows.innerHTML = rows.length ? rows.map((task) => {
      const flagged = Number(task.flagged || 0);
      const runs = Number(task.runs || 0);
      const rate = runs ? flagged / runs : 0;
      const health = rate > .15 ? "critical" : rate > .05 ? "watch" : "good";
      const label = health === "critical" ? "At risk" : health === "watch" ? "Monitor" : "Healthy";
      return `<tr><td>${escapeHtml(task.task)}</td><td>${number(runs)}</td><td>${number(flagged)}</td><td><div class="failure-rate-cell"><span>${percent(rate)}</span><i><b class="${health}" style="width:${Math.min(100, rate * 100)}%"></b></i></div></td><td>${Number(task.avg_duration || 0).toFixed(1)}s</td><td><span class="health-pill ${health}">${label}</span></td></tr>`;
    }).join("") : '<tr><td colspan="6" class="empty-row">No tasks match that search.</td></tr>';
  }

  function renderRisks(risks, tasks = []) {
    const riskSummary = $("#risk-summary");
    const riskList = $("#risk-list");
    if (!riskList) return;
    if (!risks.length) {
      if (riskSummary) riskSummary.innerHTML = "";
      riskList.innerHTML = '<div class="empty-row">No bottleneck predictions are available.</div>';
      return;
    }
    const scores = risks.map((risk) => Math.max(0, Math.min(1, Number(risk.risk || 0))));
    const high = scores.filter((score) => score >= .75).length;
    const taskAverages = new Map(tasks.map((task) => [String(task.task), Number(task.avg_duration || 0)]));
    const aboveBaseline = risks.filter((risk) => {
      const threshold = Number(risk.duration_threshold) || taskAverages.get(String(risk.task)) || 0;
      return threshold > 0 && Number(risk.duration) > threshold;
    }).length;
    if (riskSummary) riskSummary.innerHTML = [
      ["Candidates ranked", number(risks.length), "Top model-scored runs"],
      ["High priority", number(high), "Score at or above 75%"],
      ["Above task baseline", number(aboveBaseline), "Runtime exceeds its available task reference"],
      ["Highest score", percent(Math.max(...scores)), "Model review signal"]
    ].map(([label, value, caption]) => `<article class="metric-card risk-stat-card"><div class="metric-top">${label}</div><div class="metric-value">${value}</div><div class="subtle-caption">${caption}</div></article>`).join("");
    riskList.innerHTML = risks.map((risk, index) => {
      const score = Math.max(0, Math.min(1, Number(risk.risk || 0)));
      const severity = score >= .75 ? "high" : score >= .45 ? "medium" : "low";
      const learnedThreshold = Number(risk.duration_threshold || 0);
      const threshold = learnedThreshold || taskAverages.get(String(risk.task)) || 0;
      const duration = Number(risk.duration || 0);
      const baseline = threshold > 0 ? duration > threshold
        ? `${((duration / threshold - 1) * 100).toFixed(0)}% above ${learnedThreshold ? "learned threshold" : "task average"} (${threshold.toFixed(1)}s)`
        : `${(duration / threshold * 100).toFixed(0)}% of ${learnedThreshold ? "learned threshold" : "task average"} (${threshold.toFixed(1)}s)`
        : "No task threshold available";
      const timestamp = String(risk.timestamp || "").replace("T", " ").slice(0, 16);
      return `<div class="risk-item ${severity}">
        <span class="risk-rank">${String(index + 1).padStart(2, "0")}</span>
        <div class="risk-main"><div class="risk-item-top"><div><div class="risk-task">${escapeHtml(risk.task)}</div><div class="risk-meta">${escapeHtml(timestamp)}</div></div><span class="risk-priority ${severity}">${severity === "high" ? "High priority" : severity === "medium" ? "Review" : "Lower"}</span></div>
          <div class="risk-baseline">Runtime <strong>${duration.toFixed(1)}s</strong><span>·</span>${baseline}</div>
          <div class="risk-track" role="img" aria-label="Bottleneck score ${percent(score)}"><span style="width:${Math.round(score * 100)}%"></span></div>
        </div>
        <div class="risk-score"><strong>${percent(score)}</strong><span>model score</span></div>
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
        await loadAirflowStatus();
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
    const summaryElement = $("#monitor-summary");
    if (summaryElement) summaryElement.innerHTML = cards.map(([label, value]) =>
      `<article class="metric-card"><div class="metric-top">${escapeHtml(label)}</div><div class="metric-value">${escapeHtml(value)}</div></article>`
    ).join("");
    const records = Array.isArray(recovery.records) ? recovery.records : [];
    const eventsElement = $("#monitor-events");
    if (eventsElement) eventsElement.innerHTML = records.length ? records.map((record) => {
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
    const logsElement = $("#monitor-logs");
    if (logsElement) logsElement.textContent = logEntries.length
      ? logEntries.join("\n")
      : "No non-demo execution log entries yet. Recovery-demo attempts are summarized above.";
  }

  function renderAirflow(data) {
    const state = data.status || {};
    const status = $("#airflow-status");
    const retryButton = $("#airflow-retry");
    const configNote = $("#airflow-config-note");
    const failureTable = $("#airflow-failures");
    const eventsElement = $("#airflow-events");
    const configured = state.configured === true;
    const ready = state.ready_for_automation === true;
    if (status) status.textContent = data.error
      ? data.error
      : configured
        ? `Connected to Airflow ${String(state.api_version || "").toUpperCase()}${ready ? " · automatic retries enabled" : " · read-only until retry policy is enabled"}`
        : "Not connected · setup required";
    if (configNote) configNote.textContent = configured
      ? `Approved DAGs: ${(state.dag_allowlist || []).join(", ") || "none"}. Approved tasks: ${(state.task_allowlist || []).join(", ") || "none"}. Allowlist only idempotent tasks safe to rerun; inputs and connections are never modified.`
      : "Set AIRFLOW_API_URL and API version. Airflow 2 commonly uses basic auth; Airflow 3 uses jwt auth (username/password token exchange) or a pre-issued bearer token. Add DAG and task allowlists before enabling retries.";
    if (retryButton) retryButton.disabled = !ready || Boolean(data.error);
    const failures = Array.isArray(data.failed_tasks) ? data.failed_tasks : [];
    if (failureTable) failureTable.innerHTML = failures.length ? failures.map((task) => `
      <tr><td>${escapeHtml(task.dag_id || "")}</td><td>${escapeHtml(task.dag_run_id || "")}</td>
      <td>${escapeHtml(task.task_id || "")}</td><td>${escapeHtml(task.state || "failed")}</td>
      <td>${escapeHtml(task.try_number ?? "—")}</td></tr>`).join("")
      : `<tr><td colspan="5" class="empty-row">${configured && !data.error ? "No failed tasks in the approved DAGs." : "Airflow task data is unavailable until the connection is configured."}</td></tr>`;
    const events = Array.isArray(data.events) ? data.events : [];
    if (eventsElement) eventsElement.innerHTML = events.length ? `<strong>Recent Airflow recovery actions</strong>${events.slice(0, 5).map((event) =>
      `<div>${escapeHtml(event.time || "")} · ${escapeHtml(event.dag_id || "")} / ${escapeHtml(event.task_id || "")} · ${escapeHtml(event.status || "")} · ${escapeHtml(event.detail || "")}</div>`
    ).join("")}` : "";
  }

  async function loadAirflowStatus() {
    try {
      const response = await fetch("/api/airflow");
      const data = await response.json();
      renderAirflow(data);
    } catch (error) {
      renderAirflow({ status: {}, error: error instanceof Error ? error.message : "Could not check Airflow." });
    }
  }

  async function retryAirflowFailures() {
    const button = $("#airflow-retry");
    if (!button) return;
    button.disabled = true;
    button.textContent = "Checking failures…";
    try {
      const data = await readResponse(await fetch("/api/airflow/retry", { method: "POST", headers: csrfHeaders() }));
      await loadAirflowStatus();
      showNotice(`${number((data.requested || []).length)} approved retry request(s) sent to Airflow.`, "Airflow recovery complete");
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "Could not request Airflow retries.", "Airflow recovery failed");
    } finally {
      button.textContent = "Retry approved failures";
      await loadAirflowStatus();
    }
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
      const response = await fetch("/api/schedule/datasets", { method: "POST", headers: csrfHeaders(), body: form });
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
    button.textContent = "Running recovery…";
    result.hidden = true;
    try {
      const response = await fetch("/api/recovery-demo", { method: "POST", headers: csrfHeaders() });
      const data = await readResponse(response);
      const recovery = data.recovery || {};
      result.textContent = `Recovery demo complete · ${number(data.rows_loaded)} rows loaded · ${number(recovery.recovered || 0)} tasks recovered on retry · ${number(recovery.non_recoverable || 0)} issue${Number(recovery.non_recoverable || 0) === 1 ? "" : "s"} escalated as expected.`;
      result.hidden = false;
      if (activeTab === "monitor") await loadTabData("monitor");
    } catch (error) {
      const message = error instanceof TypeError
        ? "Can’t reach the PipelineIQ server. Make sure the Flask app is running at http://127.0.0.1:5000, then reload this page."
        : error instanceof Error
          ? error.message
          : "The recovery couldn’t be completed.";
      showNotice(message, "Recovery failed");
    } finally {
      button.disabled = false;
      button.innerHTML = 'Run recovery <span aria-hidden="true">→</span>';
    }
  }

  async function logout() {
    const button = $("#logout-button");
    button.disabled = true;
    try {
      const response = await fetch("/api/auth/logout", { method: "POST", headers: csrfHeaders() });
      await readResponse(response);
      window.location.assign("/auth");
    } catch (error) {
      const message = error instanceof TypeError
        ? "Can’t reach the server to end this session. Check that the app is running and try again."
        : error instanceof Error
          ? error.message
          : "Could not log out.";
      showNotice(message, "Log out failed");
      button.disabled = false;
    }
  }

  async function loadAccountProfile() {
    const nameElement = $("#profile-name") || $(".profile-copy strong");
    const avatarElement = $("#profile-avatar") || $(".profile .avatar");
    if (!nameElement) return;
    try {
      const response = await fetch("/api/auth/me", { cache: "no-store" });
      const payload = await readResponse(response);
      const user = payload.user || {};
      const fullName = String(user.name || "").trim();
      const emailName = String(user.email || "").split("@")[0].trim();
      const displayName = !fullName || fullName.toLowerCase() === "pipeline demo"
        ? emailName || "Account"
        : fullName;
      nameElement.textContent = displayName;
      nameElement.title = displayName;
      if (avatarElement) avatarElement.textContent = displayName.slice(0, 2).toUpperCase();
      const stateElement = $("#profile-state");
      if (stateElement) stateElement.textContent = "Signed in";
    } catch {
      // Keep the server-rendered session name visible if the profile endpoint is unavailable.
    }
  }

  // Bind primary navigation before optional controls so an older cached template
  // missing a newer control cannot prevent the sidebar from working.
  const sideNav = $(".side-nav");
  sideNav?.addEventListener("click", (event) => {
    const link = event.target.closest?.("a[data-tab]");
    if (!link || !sideNav.contains(link)) return;
    event.preventDefault();
    activateTab(link.dataset.tab);
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  sideNav?.addEventListener("keydown", (event) => {
    const links = [...sideNav.querySelectorAll("[data-tab]")];
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

  let logoutButton = $("#logout-button");
  if (!logoutButton) {
    const oldProfileMenu = $(".profile-menu");
    if (oldProfileMenu) {
      logoutButton = document.createElement("button");
      logoutButton.id = "logout-button";
      logoutButton.type = "button";
      logoutButton.className = "profile-logout";
      logoutButton.setAttribute("aria-label", "Log out");
      logoutButton.title = "Log out";
      logoutButton.textContent = "Log out";
      oldProfileMenu.replaceWith(logoutButton);
    }
  }
  logoutButton?.addEventListener("click", logout);

  runButtons.forEach((button) => button.addEventListener("click", runAnalysis));
  $("#schedule-source").addEventListener("change", syncScheduleSourceControls);
  $("#upload-schedule-csv").addEventListener("click", uploadScheduleCsv);
  $("#recovery-button").addEventListener("click", runRecoveryDemo);
  $("#monitor-recovery-button").addEventListener("click", runRecoveryDemo);
  $("#airflow-refresh")?.addEventListener("click", loadAirflowStatus);
  $("#airflow-retry")?.addEventListener("click", retryAirflowFailures);
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
        headers: { ...csrfHeaders(), "Content-Type": "application/json" },
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
  void loadAccountProfile();
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
  $("#task-search")?.addEventListener("input", updateTaskTable);
  $("#task-sort")?.addEventListener("change", updateTaskTable);
  fileInput.addEventListener("change", () => {
    const file = fileInput.files && fileInput.files[0];
    $("#file-label").textContent = file ? file.name : "Choose CSV";
    $("#source-note").textContent = file
      ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`
      : "Required: timestamp, task_id, status, duration, CPU, memory, I/O, and latency.";
  });

})();
