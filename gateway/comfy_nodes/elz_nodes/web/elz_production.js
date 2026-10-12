// Elz "Production" extension for ComfyUI: one-click Auto Production presets (Trailer, Product ad, Music video, Documentary, Social vertical).
// Each button makes sure an "Auto Production" workflow is open (ElzProductionPrompt in the graph), then sets its dropdowns and the video size.
// Everything is feature-detected and wrapped in try/catch, so a frontend change degrades to "nothing happens". No external requests, no eval:
// the only network call is ComfyUI's own api.fetchApi to the same server, to read a workflow you copied into user/default/workflows.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const TAG = "[elz.production]";
const NODE_TYPE = "ElzProductionPrompt";
const WORKFLOWS = {
    two: "Auto_Production_T2V_I2V_Two_Stage_Distilled.json",
    single: "Auto_Production_T2V_I2V_Single_Stage_Distilled.json",
};
const PANEL_ID = "elz-production-panel";
// Mirrors cheatsheets/production_presets.json (tests/test_elz_production.py keeps the two identical).
const PRESETS = /*PRESETS_BEGIN*/{
 "trailer": {
  "label": "Trailer",
  "style": "trailer-epic",
  "grade": "teal-orange",
  "sound": "music-orchestral",
  "effects": "speed-ramp",
  "camera": "crane-up",
  "lighting": "rim-light",
  "shot": "wide-establishing",
  "length_seconds": 6,
  "width": 1024,
  "height": 576,
  "idea": "A lone hero stands on a ridge as a vast storm gathers over the valley below."
 },
 "product-ad": {
  "label": "Product ad",
  "style": "commercial-product",
  "grade": "clean-commercial",
  "sound": "foley-detail",
  "effects": "none",
  "camera": "orbit",
  "lighting": "studio-high-key",
  "shot": "product-hero",
  "length_seconds": 5,
  "width": 1024,
  "height": 576,
  "idea": "A glass bottle of cold sparkling water sits on a wet black surface, condensation beading on the glass."
 },
 "music-video": {
  "label": "Music video",
  "style": "music-video",
  "grade": "night-neon",
  "sound": "music-upbeat",
  "effects": "lens-flare",
  "camera": "tracking",
  "lighting": "neon-glow",
  "shot": "medium",
  "length_seconds": 6,
  "width": 1024,
  "height": 576,
  "idea": "A singer performs on a rooftop at night, dancing to the beat as the city lights glow behind her."
 },
 "documentary": {
  "label": "Documentary",
  "style": "documentary",
  "grade": "natural-neutral",
  "sound": "voiceover",
  "effects": "none",
  "camera": "handheld-follow",
  "lighting": "overcast",
  "shot": "medium",
  "length_seconds": 8,
  "width": 1024,
  "height": 576,
  "idea": "A craftsman works at a wooden bench in his workshop, shaping a chair leg with a hand plane."
 },
 "social-vertical": {
  "label": "Social vertical",
  "style": "social-ugc",
  "grade": "golden-hour",
  "sound": "music-upbeat",
  "effects": "none",
  "camera": "static-tripod",
  "lighting": "golden-backlight",
  "shot": "close-up",
  "length_seconds": 5,
  "width": 576,
  "height": 1024,
  "idea": "A young woman holds up a coffee cup toward the camera, smiling, and says, \"This is my new morning ritual.\""
 }
}/*PRESETS_END*/;
const ORDER = ["trailer", "product-ad", "music-video", "documentary", "social-vertical"];
const COMBOS = ["style", "grade", "sound", "effects", "camera", "lighting", "shot"];

function say(severity, summary, detail) {
    try {
        const toast = app.extensionManager && app.extensionManager.toast;
        if (toast && typeof toast.add === "function") {
            toast.add({ severity, summary, detail, life: 6000 });
            return;
        }
    } catch (err) {
        console.warn(TAG, "toast unavailable", err);
    }
    console.info(TAG, summary, detail || "");
}

function graphNodes() {
    try {
        return (app.graph && app.graph._nodes) || [];
    } catch (err) {
        return [];
    }
}

function findProductionNode() {
    return graphNodes().find((n) => n && n.type === NODE_TYPE) || null;
}

function widgetOf(node, name) {
    return node && Array.isArray(node.widgets) ? node.widgets.find((w) => w && w.name === name) : null;
}

function setWidget(node, name, value) {
    const w = widgetOf(node, name);
    if (!w || value === undefined) return false;
    try {
        if (w.options && Array.isArray(w.options.values) && !w.options.values.includes(value)) {
            console.warn(TAG, "value not offered by", name, value);
            return false;
        }
        w.value = value;
        if (typeof w.callback === "function") w.callback(value);
        return true;
    } catch (err) {
        console.warn(TAG, "could not set", name, err);
        return false;
    }
}

// The video size widgets live on the "Preprocess" subgraph node of the Auto Production workflows (presets/ltx25/auto/*.json: subgraph id below, widgets
// labelled "video width" / "video height"). Only that node is touched; any other node with width/height widgets is left alone.
const SIZE_SUBGRAPH_ID = "792f0fd8-129e-48eb-9904-8d1aa82154d1";

function setSize(width, height) {
    let done = false;
    for (const n of graphNodes()) {
        try {
            if (!n || n.type !== SIZE_SUBGRAPH_ID) continue;
            const w = widgetOf(n, "width");
            const h = widgetOf(n, "height");
            if (w && h && typeof w.value === "number" && typeof h.value === "number") {
                w.value = width;
                h.value = height;
                done = true;
            }
        } catch (err) {
            console.warn(TAG, "size not set on a node", err);
        }
    }
    return done;
}

async function loadWorkflow(file) {
    if (!app || typeof app.loadGraphData !== "function" || !api || typeof api.fetchApi !== "function") return false;
    try {
        const res = await api.fetchApi("/userdata/" + encodeURIComponent("workflows/" + file));
        if (!res || !res.ok) return false;
        await app.loadGraphData(await res.json(), true, true, file.replace(/\.json$/, ""));
        return true;
    } catch (err) {
        console.warn(TAG, "could not load", file, err);
        return false;
    }
}

function applyPreset(key, node) {
    const p = PRESETS[key];
    if (!p || !node) return false;
    for (const c of COMBOS) setWidget(node, c, p[c]);
    setWidget(node, "length_seconds", p.length_seconds);
    setWidget(node, "auto", true);
    if (p.idea && !(widgetOf(node, "idea") && widgetOf(node, "idea").value)) setWidget(node, "idea", p.idea);
    if (p.width && p.height) setSize(p.width, p.height);
    try {
        node.setDirtyCanvas(true, true);
        if (app.graph && typeof app.graph.setDirtyCanvas === "function") app.graph.setDirtyCanvas(true, true);
    } catch (err) {
        console.warn(TAG, "redraw failed", err);
    }
    return true;
}

async function runPreset(key, variant) {
    try {
        const p = PRESETS[key];
        if (!p) return;
        let node = findProductionNode();
        if (!node) {
            const ok = await loadWorkflow(WORKFLOWS[variant === "single" ? "single" : "two"]);
            node = ok ? findProductionNode() : null;
        }
        if (!node) {
            say("warn", "Auto Production workflow not open", "Copy presets/ltx25/auto/*.json into ComfyUI/user/default/workflows, then press the button again (or open one from the Workflows list).");
            return;
        }
        applyPreset(key, node);
        say("success", p.label + " preset set", "Edit the idea box and press Run. Dropdowns left on auto are picked from your idea.");
    } catch (err) {
        console.warn(TAG, "preset failed", key, err);
    }
}

function buildPanel(el) {
    try {
        el.innerHTML = "";
        const box = document.createElement("div");
        box.id = PANEL_ID;
        box.style.cssText = "padding:10px;display:flex;flex-direction:column;gap:8px;font-size:13px;";
        const title = document.createElement("div");
        title.textContent = "Auto Production";
        title.style.cssText = "font-weight:600;font-size:15px;";
        const hint = document.createElement("div");
        hint.textContent = "One click sets style, grade, sound, effects, camera, lighting and shot. Leave a dropdown on auto to let your idea choose.";
        hint.style.opacity = "0.75";
        const sel = document.createElement("select");
        for (const [v, t] of [["two", "Two-stage (higher quality)"], ["single", "Single-stage (faster)"]]) {
            const o = document.createElement("option");
            o.value = v;
            o.textContent = t;
            sel.appendChild(o);
        }
        box.append(title, hint, sel);
        for (const key of ORDER) {
            const p = PRESETS[key];
            if (!p) continue;
            const b = document.createElement("button");
            b.type = "button";
            b.textContent = p.label;
            b.title = [p.style, p.grade, p.sound, p.camera, p.lighting].join(" / ");
            b.style.cssText = "padding:8px;cursor:pointer;text-align:left;";
            b.addEventListener("click", () => runPreset(key, sel.value));
            box.appendChild(b);
        }
        el.appendChild(box);
    } catch (err) {
        console.warn(TAG, "panel failed", err);
    }
}

app.registerExtension({
    name: "elz.production",
    async setup() {
        try {
            const mgr = app.extensionManager;
            if (mgr && typeof mgr.registerSidebarTab === "function") {
                mgr.registerSidebarTab({
                    id: "elzProduction",
                    icon: "pi pi-video",
                    title: "Production",
                    tooltip: "Auto Production presets",
                    type: "custom",
                    render: (el) => buildPanel(el),
                });
            }
        } catch (err) {
            console.warn(TAG, "sidebar tab unavailable", err);
        }
    },
    // Menu fallback for frontends without sidebar tabs: commands show up in the command palette / extension menus.
    commands: ORDER.filter((k) => PRESETS[k]).map((k) => ({
        id: "Elz.Production." + k,
        label: "Production: " + PRESETS[k].label,
        function: () => runPreset(k, "two"),
    })),
    menuCommands: [{ path: ["Production"], commands: ORDER.filter((k) => PRESETS[k]).map((k) => "Elz.Production." + k) }],
});
