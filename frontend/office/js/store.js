// AlphaOS Office — session store with localStorage persistence + pub/sub
const KEY = "alphaos.office.v1";

const defaults = () => ({
  onboarded: false,
  mode: "demo", // demo | live
  agentEnabled: { manager: true, macro: true, research: true, quant: true, risk: true, report: true },
  tasks: [],
  currentTaskId: null,
  followups: {},
});

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return defaults();
    return { ...defaults(), ...JSON.parse(raw) };
  } catch {
    return defaults();
  }
}

const listeners = new Map();

export const store = {
  state: load(),

  persist() {
    try {
      localStorage.setItem(KEY, JSON.stringify(this.state));
    } catch {
      /* storage unavailable — session-only */
    }
  },

  on(event, cb) {
    if (!listeners.has(event)) listeners.set(event, new Set());
    listeners.get(event).add(cb);
    return () => listeners.get(event)?.delete(cb);
  },

  emit(event, payload) {
    listeners.get(event)?.forEach((cb) => cb(payload));
  },

  set(patch) {
    Object.assign(this.state, patch);
    this.persist();
  },

  setAgentEnabled(id, enabled) {
    this.state.agentEnabled[id] = enabled;
    this.persist();
    this.emit("agentEnabled", { id, enabled });
  },

  addTask(task) {
    this.state.tasks.unshift(task);
    this.state.currentTaskId = task.id;
    this.persist();
    this.emit("tasks", this.state.tasks);
  },

  updateTask(id, patch) {
    const task = this.state.tasks.find((t) => t.id === id);
    if (task) {
      Object.assign(task, patch);
      this.persist();
      this.emit("tasks", this.state.tasks);
    }
  },

  currentTask() {
    return this.state.tasks.find((t) => t.id === this.state.currentTaskId) || null;
  },

  addFollowup(reportId, msg) {
    if (!this.state.followups[reportId]) this.state.followups[reportId] = [];
    this.state.followups[reportId].push(msg);
    this.persist();
  },

  resetAll() {
    try {
      localStorage.removeItem(KEY);
    } catch {
      /* noop */
    }
    this.state = defaults();
  },
};
