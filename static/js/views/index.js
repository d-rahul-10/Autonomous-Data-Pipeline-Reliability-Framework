/**
 * PipelineIQ Views
 * View registry - each view is a render function(container, data) -> void.
 * Views are pure renderers: they receive data and write DOM, never fetch.
 */

import { renderDashboard } from "./dashboard.js";
import { renderHealth } from "./health.js";
import { renderRisk } from "./risk.js";
import { renderQuality } from "./quality.js";
import { renderPerformance } from "./performance.js";
import { renderMonitor } from "./monitor.js";
import { renderReports } from "./reports.js";
import { renderScheduler } from "./scheduler.js";

export const views = {
  overview: renderDashboard,
  health: renderHealth,
  risk: renderRisk,
  quality: renderQuality,
  performance: renderPerformance,
  monitor: renderMonitor,
  reports: renderReports,
  scheduler: renderScheduler,
};
