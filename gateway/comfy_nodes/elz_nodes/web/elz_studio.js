// Elz front-end extension for ComfyUI (ComfyUI v2 = the stock UI plus this file; no fork).
// Adds: a Studio link, a queue/elapsed badge, a Release GPU hint, and node colours for LTX* and Elz* nodes.
// Every feature is feature-detected and wrapped so a frontend change degrades to "nothing happens", never a broken UI.
// No network requests are made from here; the only URL is the Studio page on the same host, opened in a new tab.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const STUDIO_PORT = 8447;
const STUDIO_PATH = "/approvals/studio";
const BADGE_ID = "elz-studio-badge";
const COLOUR_PRESETS = {
    ltx: { color: "#2a3b4c", bgcolor: "#1f2d3a" },
    elz: { color: "#3b2a4c", bgcolor: "#2d1f3a" },
};

const state = { queueRemaining: null, startedAt: null, timer: null };

function studioUrl() {
    const host = (window.location && window.location.hostname) || "";
    if (!host) return null;
    return "https://" + host + ":" + STUDIO_PORT + STUDIO_PATH;
}

function openStudio() {
    try {
        const url = studioUrl();
        if (!url) return;
        window.open(url, "_blank", "noopener");
    } catch (err) {
        console.warn("[elz.studio] could not open Studio", err);
    }
}

function releaseGpuHint() {
    const text = "To free GPU memory, stop the ComfyUI session from Studio (Elz Studio, port " + STUDIO_PORT + "). This button does not stop anything itself.";
    try {
        const toast = app.extensionManager && app.extensionManager.toast;
        if (toast && typeof toast.add === "function") {
            toast.add({ severity: "info", summary: "Release GPU", detail: text, life: 8000 });
            return;
        }
    } catch (err) {
        console.warn("[elz.studio] toast unavailable", err);
    }
    try {
        window.alert(text);
    } catch (err) {
        console.info("[elz.studio] " + text);
    }
}

// ---------- badge: queue remaining + elapsed time of the running prompt ----------

function ensureBadge() {
    let el = document.getElementById(BADGE_ID);
    if (el) return el;
    el = document.createElement("div");
    el.id = BADGE_ID;
    el.setAttribute("role", "status");
    el.style.cssText = "position:fixed;right:12px;bottom:12px;z-index:9999;padding:4px 8px;border-radius:6px;" +
        "font:12px/1.3 system-ui,sans-serif;color:#e8e8e8;background:rgba(20,20,28,0.85);border:1px solid #3b2a4c;" +
        "user-select:none;display:flex;gap:8px;align-items:center;";
    const label = document.createElement("span");
    label.className = "elz-badge-label";
    label.textContent = "Elz: idle";
    const hint = document.createElement("button");
    hint.type = "button";
    hint.textContent = "Release GPU";
    hint.title = "Stop the session from Studio to free GPU memory";
    hint.style.cssText = "font:inherit;padding:2px 6px;border-radius:4px;border:1px solid #555;background:#2a2a36;color:inherit;cursor:pointer;";
    hint.addEventListener("click", releaseGpuHint);
    const studio = document.createElement("button");
    studio.type = "button";
    studio.textContent = "Studio";
    studio.style.cssText = hint.style.cssText;
    studio.addEventListener("click", openStudio);
    el.append(label, studio, hint);
    document.body.appendChild(el);
    return el;
}

function renderBadge() {
    try {
        const el = ensureBadge();
        const label = el.querySelector(".elz-badge-label");
        const q = state.queueRemaining === null ? "?" : String(state.queueRemaining);
        let text = "Queue: " + q;
        if (state.startedAt !== null) {
            const secs = Math.max(0, Math.floor((Date.now() - state.startedAt) / 1000));
            text += " | running " + secs + "s";
        }
        label.textContent = text;
    } catch (err) {
        console.warn("[elz.studio] badge update failed", err);
    }
}

function startClock() {
    try {
        state.startedAt = Date.now();
        if (state.timer === null) state.timer = setInterval(renderBadge, 1000);
        renderBadge();
    } catch (err) {
        console.warn("[elz.studio] clock start failed", err);
    }
}

function stopClock() {
    try {
        state.startedAt = null;
        if (state.timer !== null) {
            clearInterval(state.timer);
            state.timer = null;
        }
        renderBadge();
    } catch (err) {
        console.warn("[elz.studio] clock stop failed", err);
    }
}

function onStatus(e) {
    try {
        const d = e && e.detail;
        const info = d && (d.exec_info || (d.status && d.status.exec_info));
        if (info && typeof info.queue_remaining === "number") {
            state.queueRemaining = info.queue_remaining;
            renderBadge();
        }
    } catch (err) {
        console.warn("[elz.studio] status event ignored", err);
    }
}

function wireApi() {
    try {
        if (!api || typeof api.addEventListener !== "function") return;
        api.addEventListener("status", onStatus);
        api.addEventListener("execution_start", startClock);
        api.addEventListener("execution_success", stopClock);
        api.addEventListener("execution_error", stopClock);
        api.addEventListener("execution_interrupted", stopClock);
        // ComfyUI sends "executing" with node == null when the whole prompt has finished.
        api.addEventListener("executing", (e) => {
            try { if (e && e.detail == null) stopClock(); } catch (err) { /* fail soft */ }
        });
    } catch (err) {
        console.warn("[elz.studio] api hooks unavailable", err);
    }
}

// ---------- menu entries (feature-detected; the menu API differs between frontend versions) ----------

async function addTopMenuButton() {
    try {
        const group = app.menu && (app.menu.actionsGroup || app.menu.settingsGroup);
        if (!group || typeof group.append !== "function") return false;
        const mod = await import("../../scripts/ui/components/button.js");
        const ComfyButton = mod && mod.ComfyButton;
        if (typeof ComfyButton !== "function") return false;
        const btn = new ComfyButton({ icon: "open-in-new", tooltip: "Open Elz Studio in a new tab", content: "Studio", action: openStudio });
        group.append(btn);
        return true;
    } catch (err) {
        return false;
    }
}

function registerCommands() {
    try {
        const reg = app.extensionManager && app.extensionManager.registerCommand;
        if (typeof reg !== "function") return false;
        reg.call(app.extensionManager, { id: "elz.studio.open", label: "Elz: Open Studio", function: openStudio });
        reg.call(app.extensionManager, { id: "elz.studio.releaseGpu", label: "Elz: Release GPU (hint)", function: releaseGpuHint });
        return true;
    } catch (err) {
        return false;
    }
}

// ---------- node colours ----------

function colourCategory(node) {
    const type = String((node && (node.type || node.comfyClass)) || "");
    if (/^LTX/i.test(type)) return COLOUR_PRESETS.ltx;
    if (/^Elz/.test(type)) return COLOUR_PRESETS.elz;
    return null;
}

function colourNode(node) {
    try {
        const preset = colourCategory(node);
        if (!preset) return;
        node.color = preset.color;
        node.bgcolor = preset.bgcolor;
    } catch (err) {
        /* fail soft: an uncoloured node is fine */
    }
}

function colourGraph() {
    try {
        const nodes = (app.graph && (app.graph._nodes || app.graph.nodes)) || [];
        for (const node of nodes) colourNode(node);
        if (app.graph && typeof app.graph.setDirtyCanvas === "function") app.graph.setDirtyCanvas(true, true);
    } catch (err) {
        console.warn("[elz.studio] colouring graph skipped", err);
    }
}

app.registerExtension({
    name: "elz.studio",
    async setup() {
        try {
            wireApi();
            ensureBadge();
            renderBadge();
            const viaMenu = await addTopMenuButton();
            if (!viaMenu) registerCommands();
        } catch (err) {
            console.warn("[elz.studio] setup skipped", err);
        }
    },
    nodeCreated(node) {
        colourNode(node);
    },
    afterConfigureGraph() {
        colourGraph();
    },
});
