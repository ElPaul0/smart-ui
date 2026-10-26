(function () {
  const cfg = window.SMART_UI_CONFIG || {};
  const I18N = window.SMART_UI_I18N || {};
  const THEME_KEY = "smart-ui-theme";
  const LANG_KEY = "smart-ui-lang";
  const REFRESH_KEY = "smart-ui-refresh-sec";
  const REFRESH_OPTIONS = [10, 30, 60, 120];

  let theme = localStorage.getItem(THEME_KEY) || cfg.defaultTheme || "dark";
  let lang = localStorage.getItem(LANG_KEY) || cfg.defaultLang || "en";
  let refreshSec = parseInt(localStorage.getItem(REFRESH_KEY) || cfg.defaultRefreshSec || 30, 10);
  if (!REFRESH_OPTIONS.includes(refreshSec)) refreshSec = 30;
  if (!I18N[lang]) lang = "en";
  if (theme !== "light" && theme !== "dark") theme = "dark";

  let refreshTimer = null;
  let shellBuilt = false;
  let lastSig = "";

  const VD_BAD = new Set(["Dgrd", "Pdgd", "OfLn", "Offln", "Offline", "Failed"]);
  const PD_OK = new Set(["Onln", "Online"]);

  function t(key) {
    return (I18N[lang] && I18N[lang][key]) || (I18N.en && I18N.en[key]) || key;
  }

  function el(id) {
    return document.getElementById(id);
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatTemplate(template, params) {
    return String(template).replace(/\{(\w+)\}/g, (_, key) =>
      params[key] != null ? String(params[key]) : ""
    );
  }

  function applyTheme() {
    document.documentElement.setAttribute("data-theme", theme);
    document.querySelectorAll("[data-theme-btn]").forEach((btn) => {
      btn.setAttribute("aria-pressed", btn.dataset.themeBtn === theme ? "true" : "false");
    });
  }

  function applyLangChrome() {
    document.documentElement.lang = lang;
    const testBtn = el("testBtn");
    if (testBtn && !testBtn.disabled) testBtn.textContent = "🧪 " + t("test_notify");
    document.querySelectorAll("[data-lang-btn]").forEach((btn) => {
      btn.setAttribute("aria-pressed", btn.dataset.langBtn === lang ? "true" : "false");
    });
    const darkBtn = document.querySelector('[data-theme-btn="dark"]');
    const lightBtn = document.querySelector('[data-theme-btn="light"]');
    if (darkBtn) darkBtn.textContent = t("theme_dark");
    if (lightBtn) lightBtn.textContent = t("theme_light");
    const refreshLabel = el("refreshLabel");
    if (refreshLabel) refreshLabel.textContent = t("refresh");
    if (shellBuilt) {
      setText("lbl-controller", "🖥️ " + t("controller"));
      setText("lbl-vd", "📀 " + t("virtual_drives"));
      setText("lbl-pd", "💾 " + t("physical_drives"));
      setText("lbl-events", "📋 " + t("events"));
    }
  }

  function setText(id, value) {
    const node = el(id);
    if (!node) return;
    const next = value == null ? "" : String(value);
    if (node.textContent !== next) node.textContent = next;
  }

  function setTheme(next) {
    theme = next;
    localStorage.setItem(THEME_KEY, theme);
    applyTheme();
  }

  function setLang(next) {
    lang = next;
    localStorage.setItem(LANG_KEY, lang);
    applyLangChrome();
    lastSig = "";
    refresh();
  }

  function scheduleRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(refresh, refreshSec * 1000);
  }

  function setRefreshSec(sec) {
    refreshSec = sec;
    localStorage.setItem(REFRESH_KEY, String(refreshSec));
    const select = el("refreshSelect");
    if (select) select.value = String(refreshSec);
    scheduleRefresh();
  }

  function statusClassForCtrl(status) {
    if (status === "Optimal") return "status-optimal";
    if (status === "Degraded") return "status-degraded";
    return "status-failed";
  }

  function statusClassForVd(state) {
    if (state === "Optl" || state === "Optimal") return "status-optimal";
    if (VD_BAD.has(state) && (state === "Dgrd" || state === "Pdgd")) return "status-degraded";
    if (VD_BAD.has(state)) return "status-failed";
    return "status-degraded";
  }

  function statusClassForPd(state) {
    if (PD_OK.has(state)) return "status-optimal";
    if (state === "Failed" || state === "Offln" || state === "Offline" || state === "UBad") {
      return "status-failed";
    }
    return "status-degraded";
  }

  function formatEventMessage(event) {
    let key = event.key;
    let params = event.params || {};
    if (!key) return event.message || "";
    const template = t("evt_" + key);
    if (!template || template === "evt_" + key) return event.message || key;
    return formatTemplate(template, params);
  }

  function ensureShell() {
    if (shellBuilt) return;
    const content = el("content");
    content.classList.remove("loading");
    content.innerHTML = `
      <div id="errorBanner" class="error-banner" hidden></div>
      <div id="dashboard" hidden>
        <div class="card">
          <h2 id="lbl-controller"></h2>
          <div class="controller-row" id="val-controller"></div>
        </div>
        <div class="card">
          <h2 id="lbl-vd"></h2>
          <div class="vd-grid" id="val-vd"></div>
        </div>
        <div class="card">
          <h2 id="lbl-pd"></h2>
          <div class="drives-grid" id="val-pd"></div>
        </div>
        <div class="card">
          <h2 id="lbl-events"></h2>
          <div class="events" id="val-events"></div>
        </div>
      </div>
    `;
    shellBuilt = true;
    applyLangChrome();
  }

  function showError(message) {
    ensureShell();
    el("errorBanner").hidden = false;
    el("dashboard").hidden = true;
    el("errorBanner").innerHTML =
      `<strong>${t("storcli_error")}</strong><br>${escapeHtml(message)}`;
  }

  function showDashboard() {
    ensureShell();
    el("errorBanner").hidden = true;
    el("dashboard").hidden = false;
  }

  function renderController(c) {
    const status = c.status || t("state_unknown");
    let statusLabel = status;
    if (status === "Optimal") statusLabel = t("state_optimal");
    else if (status === "Degraded") statusLabel = t("state_degraded");

    return `
      <div class="ctrl-item">
        <div class="label">${escapeHtml(t("controller"))}</div>
        <div class="value">${escapeHtml(c.model || "N/A")}</div>
      </div>
      <div class="ctrl-item">
        <div class="label">${escapeHtml(t("status"))}</div>
        <span class="status-badge ${statusClassForCtrl(status)}">${escapeHtml(statusLabel)}</span>
      </div>
      <div class="ctrl-item">
        <div class="label">${escapeHtml(t("firmware"))}</div>
        <div class="value">${escapeHtml(c.fw || "N/A")}</div>
      </div>
      <div class="ctrl-item">
        <div class="label">${escapeHtml(t("serial"))}</div>
        <div class="value mono">${escapeHtml(c.sn || "N/A")}</div>
      </div>
    `;
  }

  function renderVd(list) {
    if (!list || !list.length) {
      return `<div class="empty">${escapeHtml(t("no_vd"))}</div>`;
    }
    return list
      .map(
        (vd) => `
      <div class="vd-card">
        <div class="vd-title">${escapeHtml(vd.dgvd || "?")}</div>
        <div class="vd-type">${escapeHtml(vd.type || "?")}</div>
        <div class="vd-size">${escapeHtml(vd.size || "?")}</div>
        <span class="status-badge ${statusClassForVd(vd.state)}">${escapeHtml(vd.state || "?")}</span>
      </div>`
      )
      .join("");
  }

  function tempClass(temp) {
    if (temp == null) return "muted";
    if (temp < 45) return "temp-ok";
    if (temp < 55) return "temp-warn";
    return "temp-crit";
  }

  function errClass(val) {
    return String(val) === "0" ? "error-ok" : "error-warn";
  }

  function renderPd(list) {
    if (!list || !list.length) {
      return `<div class="empty">${escapeHtml(t("no_pd"))}</div>`;
    }
    return list
      .map((d) => {
        const temp = d.temp;
        const tempHtml =
          temp == null
            ? `<div class="stat-value muted">—</div>`
            : `<div class="stat-value ${tempClass(temp)}">${temp}°C</div>`;
        return `
      <div class="drive-card">
        <div class="drive-header">
          <span class="drive-slot">${escapeHtml(t("slot"))} ${escapeHtml(String(d.slot ?? "?"))} — DG${escapeHtml(String(d.dg ?? "?"))}</span>
          <span class="status-badge ${statusClassForPd(d.state)}">${escapeHtml(d.state || "?")}</span>
        </div>
        <div class="drive-model">${escapeHtml(d.model || "N/A")}</div>
        <div class="drive-sn">${escapeHtml(d.sn || "")}</div>
        <div class="drive-stats">
          <div class="stat">
            <div class="stat-label">${escapeHtml(t("temp"))}</div>
            ${tempHtml}
          </div>
          <div class="stat">
            <div class="stat-label">${escapeHtml(t("size"))}</div>
            <div class="stat-value">${escapeHtml(d.size || "—")}</div>
          </div>
          <div class="stat">
            <div class="stat-label">${escapeHtml(t("media_errors"))}</div>
            <div class="stat-value ${errClass(d.media_errors)}">${escapeHtml(String(d.media_errors ?? "—"))}</div>
          </div>
          <div class="stat">
            <div class="stat-label">${escapeHtml(t("predictive"))}</div>
            <div class="stat-value ${errClass(d.predictive)}">${escapeHtml(String(d.predictive ?? "—"))}</div>
          </div>
        </div>
      </div>`;
      })
      .join("");
  }

  async function refresh() {
    try {
      const [status, events] = await Promise.all([
        fetch("/api/status").then((r) => r.json()),
        fetch("/api/events").then((r) => r.json()),
      ]);

      if (status._error) {
        showError(status._error);
        return;
      }

      showDashboard();

      const sig = lang + "|" + JSON.stringify(status) + "|" + JSON.stringify(events);
      if (sig === lastSig) return;
      lastSig = sig;

      const pdCount = (status.pdrives || []).length;
      setText("lbl-pd", "💾 " + t("physical_drives") + (pdCount ? ` (${pdCount})` : ""));

      el("val-controller").innerHTML = renderController(status.controller || {});
      el("val-vd").innerHTML = renderVd(status.vdrives || []);
      el("val-pd").innerHTML = renderPd(status.pdrives || []);

      let eventsHtml = "";
      if (!events.length) {
        eventsHtml = `<div class="event-row muted">${escapeHtml(t("no_events"))}</div>`;
      } else {
        for (const e of events) {
          eventsHtml += `<div class="event-row"><span class="event-ts">${escapeHtml(
            e.ts
          )}</span>${escapeHtml(formatEventMessage(e))}</div>`;
        }
      }
      el("val-events").innerHTML = eventsHtml;
    } catch (e) {
      showError(String(e));
    }
  }

  async function testNotify() {
    const btn = el("testBtn");
    const original = "🧪 " + t("test_notify");
    btn.textContent = "⏳ " + t("sending");
    btn.disabled = true;
    try {
      const res = await fetch("/api/test-notify");
      const data = await res.json();
      btn.textContent = data.sent ? "✅ " + t("sent") : "❌ " + t("failed");
    } catch {
      btn.textContent = "❌ " + t("error");
    }
    setTimeout(() => {
      btn.textContent = original;
      btn.disabled = false;
      lastSig = "";
      refresh();
    }, 2000);
  }

  document.addEventListener("DOMContentLoaded", () => {
    applyTheme();
    applyLangChrome();

    document.querySelectorAll("[data-theme-btn]").forEach((btn) => {
      btn.addEventListener("click", () => setTheme(btn.dataset.themeBtn));
    });
    document.querySelectorAll("[data-lang-btn]").forEach((btn) => {
      btn.addEventListener("click", () => setLang(btn.dataset.langBtn));
    });
    el("testBtn").addEventListener("click", testNotify);

    const select = el("refreshSelect");
    if (select) {
      select.value = String(refreshSec);
      select.addEventListener("change", () => {
        setRefreshSec(parseInt(select.value, 10));
      });
    }

    refresh();
    scheduleRefresh();
  });
})();
