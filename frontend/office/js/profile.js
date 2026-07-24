import { api } from "./api.js";

const STEP_KEY = "alphaos.profile.onboarding.step.v1";

const FIELD_META = {
  investment_goal: {
    label: "投资目标",
    question: "你希望这笔投资主要解决什么问题？",
    hint: "例如长期增值、资产保值、购房准备、教育支出或退休储备。",
    kind: "text",
  },
  monthly_after_tax_income_cny: {
    label: "每月税后收入",
    question: "你每月实际到手的收入大约是多少？",
    hint: "不需要精确到个位数。",
    kind: "money",
  },
  income_stability: {
    label: "收入稳定性",
    question: "你的收入通常有多稳定？",
    kind: "select",
    options: [["stable", "稳定：每月收入基本固定"], ["variable", "波动：收入会明显变化"], ["uncertain", "不确定：暂时难以判断"]],
  },
  monthly_essential_expenses_cny: {
    label: "每月必要支出",
    question: "你每月必须支付的生活费用大约是多少？",
    hint: "包括住房、基本生活、交通、医疗和家庭支出。",
    kind: "money",
  },
  monthly_debt_payment_cny: {
    label: "每月债务还款",
    question: "除日常支出外，你每月还有多少固定还款？",
    hint: "例如房贷、车贷、消费贷或信用卡分期；没有可填 0。",
    kind: "money",
  },
  dependents_count: {
    label: "家庭责任",
    question: "目前有多少人主要依赖你的收入生活？",
    hint: "例如子女、父母或其他家庭成员。",
    kind: "number",
  },
  emergency_fund_cny: {
    label: "应急资金",
    question: "目前你有多少资金专门用于失业、疾病或紧急支出？",
    hint: "不包括准备投资的钱；系统会换算为可覆盖的必要支出月数。",
    kind: "money",
  },
  planned_large_expenses_cny: {
    label: "未来大额支出",
    question: "未来一年内是否有确定的大额支出？",
    hint: "例如学费、医疗、购房首付、装修或婚礼；没有可填 0。",
    kind: "money",
  },
  planned_large_expenses_within_months: {
    label: "大额支出时间",
    question: "这笔已知大额支出大约会在几个月内发生？",
    hint: "没有已知大额支出可填 0。",
    kind: "number",
  },
  available_investment_funds_cny: {
    label: "可投资资金",
    question: "不影响生活、应急资金和已知大额支出的前提下，这次你计划投入多少资金？",
    kind: "money",
  },
  investment_horizon_months: {
    label: "投资期限",
    question: "这笔钱最早可能在什么时候需要使用？",
    hint: "请换算为月，例如 6 个月、24 个月或 60 个月。",
    kind: "number",
  },
  liquidity_need: {
    label: "流动性需求",
    question: "出现临时需要时，你是否必须很快取回这笔钱？",
    kind: "select",
    options: [["high", "高：可能随时需要"], ["medium", "中：一年内可能需要"], ["low", "低：几年内基本不会使用"]],
  },
  max_acceptable_loss_ratio: {
    label: "最大可接受亏损",
    question: "假设投入 10 万元，短期下跌多少会明显影响生活或让你必须卖出？",
    hint: "填写百分比：5000 元=5%，1 万元=10%，2 万元=20%。这不是建议承担该亏损。",
    kind: "percent",
  },
  existing_positions: {
    label: "当前持仓",
    question: "你目前有哪些存款、基金、股票、债券或其他资产？",
    hint: "每行填写：资产名称 | 类型 | 大致金额 | 占比%。也可以明确选择“目前没有持仓”。",
    kind: "positions",
  },
  investment_experience: {
    label: "投资经验",
    question: "你过去是否实际购买并持有过股票、基金或债券？",
    hint: "投资经验不会被用来自动提高你的风险承受能力。",
    kind: "select",
    options: [["none", "没有实际投资经验"], ["basic", "有一些实际持有经验"], ["experienced", "有较长时间的实际经验"]],
  },
};

const STEPS = [
  "investment_goal",
  "monthly_after_tax_income_cny",
  "income_stability",
  "monthly_essential_expenses_cny",
  "monthly_debt_payment_cny",
  "dependents_count",
  "emergency_fund_cny",
  ["planned_large_expenses_cny", "planned_large_expenses_within_months"],
  "available_investment_funds_cny",
  "investment_horizon_months",
  "liquidity_need",
  "max_acceptable_loss_ratio",
  "existing_positions",
  "investment_experience",
];
const SECTIONS = [
  { title: "现金流与家庭责任", fields: ["monthly_after_tax_income_cny", "income_stability", "monthly_essential_expenses_cny", "monthly_debt_payment_cny", "dependents_count", "emergency_fund_cny"] },
  { title: "目标与资金安排", fields: ["investment_goal", "planned_large_expenses_cny", "planned_large_expenses_within_months", "available_investment_funds_cny", "investment_horizon_months"] },
  { title: "流动性与亏损边界", fields: ["liquidity_need", "max_acceptable_loss_ratio"] },
  { title: "持仓与经验", fields: ["existing_positions", "investment_experience"] },
];

const money = (value) => value == null ? "未填写" : new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 0 }).format(value);
const percent = (value) => value == null ? "未填写" : `${(value * 100).toFixed(value * 100 % 1 ? 1 : 0)}%`;
const text = (value) => value == null || value === "" ? "未填写" : String(value);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function inputMarkup(field, value, compact = false) {
  const meta = FIELD_META[field];
  const id = `profile-${field}-${Math.random().toString(36).slice(2)}`;
  const label = compact ? `<label for="${id}">${esc(meta.label)}</label>` : "";
  if (meta.kind === "select") {
    return `${label}<select id="${id}" data-profile-field="${field}"><option value="">暂不填写</option>${meta.options.map(([v, t]) => `<option value="${v}"${value === v ? " selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
  }
  if (meta.kind === "positions") {
    const rows = Array.isArray(value) ? value.map((p) => [p.asset_name, p.asset_type, p.amount_cny ?? "", p.portfolio_ratio == null ? "" : p.portfolio_ratio * 100].join(" | ")).join("\n") : "";
    return `${label}<textarea id="${id}" data-profile-field="${field}" rows="4" placeholder="沪深300指数基金 | 基金 | 60000 | 60">${esc(rows)}</textarea><label class="profile-check"><input type="checkbox" data-no-positions${Array.isArray(value) && value.length === 0 ? " checked" : ""}> 目前明确没有持仓</label>`;
  }
  const shown = meta.kind === "percent" && value != null ? value * 100 : (value ?? "");
  const type = meta.kind === "text" ? "text" : "number";
  const step = meta.kind === "percent" ? "0.1" : "1";
  const min = field === "investment_horizon_months" ? "1" : "0";
  return `${label}<input id="${id}" data-profile-field="${field}" type="${type}" min="${min}" step="${step}" value="${esc(shown)}" placeholder="暂不填写">`;
}

function readField(root, field) {
  const meta = FIELD_META[field];
  const input = root.querySelector(`[data-profile-field="${field}"]`);
  if (!input) return null;
  if (meta.kind === "positions") {
    if (root.querySelector("[data-no-positions]")?.checked) return [];
    const raw = input.value.trim();
    if (!raw) return null;
    return raw.split(/\r?\n/).filter(Boolean).map((line) => {
      const [asset_name, asset_type, amount, ratio] = line.split("|").map((v) => v.trim());
      if (!asset_name || !asset_type || (!amount && !ratio)) throw new Error("每项持仓至少填写名称、类型，以及金额或占比。");
      return {
        asset_name,
        asset_type,
        amount_cny: amount === "" ? null : Number(amount),
        portfolio_ratio: ratio === "" ? null : Number(ratio) / 100,
      };
    });
  }
  if (meta.kind === "select" || meta.kind === "text") return input.value.trim() || null;
  if (input.value === "") return null;
  const value = Number(input.value);
  if (!Number.isFinite(value)) throw new Error(`${meta.label}格式不正确。`);
  return meta.kind === "percent" ? value / 100 : value;
}

function setError(root, message = "") {
  const node = root.querySelector("[data-profile-error]");
  if (node) node.textContent = message;
}

function profileCard(label, value) {
  return `<div class="profile-stat"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
}

export function mountProfilePage(container, notify = () => {}) {
  container.innerHTML = `<div class="profile-loading">正在读取 SQLite 中的用户画像…</div>`;
  api.userProfile().then((data) => renderProfilePage(container, data, notify)).catch((error) => {
    container.innerHTML = `<div class="panel profile-error">${esc(error.message)}</div>`;
  });
}

function renderProfilePage(container, data, notify) {
  const profile = data.profile || {};
  const derived = data.derived_metrics || {};
  const completeness = Math.round((derived.profile_completeness || 0) * 100);
  container.innerHTML = `
    <section class="profile-hero panel">
      <div><p class="profile-kicker">LOCAL SINGLE-USER MVP</p><h1>用户画像</h1><p>SQLite 是画像事实源；当前不跨设备同步，也不保存姓名、证件、银行卡、手机号或精确地址。</p></div>
      <div class="profile-completeness"><strong>${completeness}%</strong><span>画像完整度</span></div>
    </section>
    <section class="profile-stats">
      ${profileCard("每月收入", money(profile.monthly_after_tax_income_cny))}
      ${profileCard("每月必要支出", money(profile.monthly_essential_expenses_cny))}
      ${profileCard("每月债务", money(profile.monthly_debt_payment_cny))}
      ${profileCard("每月结余", money(derived.monthly_surplus_cny))}
      ${profileCard("家庭责任", profile.dependents_count == null ? "未填写" : `${profile.dependents_count} 人`)}
      ${profileCard("应急资金覆盖", derived.emergency_fund_months == null ? "未填写" : `${derived.emergency_fund_months.toFixed(1)} 个月`)}
      ${profileCard("可投资资金", money(profile.available_investment_funds_cny))}
      ${profileCard("最大亏损边界", percent(profile.max_acceptable_loss_ratio))}
    </section>
    <div class="profile-sections"></div>
    <section class="panel profile-meta">
      <div><span>画像版本</span><strong>${profile.profile_version ? `v${profile.profile_version}` : "未建立"}</strong></div>
      <div><span>更新时间</span><strong>${profile.updated_at ? new Date(profile.updated_at).toLocaleString("zh-CN") : "未保存"}</strong></div>
      <div class="profile-danger-actions"><button class="btn" data-profile-restart>重新进行建档</button><button class="btn profile-danger" data-profile-clear>清空画像</button></div>
    </section>`;

  const sections = container.querySelector(".profile-sections");
  SECTIONS.forEach((section) => {
    const panel = document.createElement("section");
    panel.className = "panel profile-section";
    panel.innerHTML = `<h2>${esc(section.title)}</h2><div class="profile-form-grid">${section.fields.map((field) => `<div class="profile-field">${inputMarkup(field, profile[field], true)}<small>${esc(FIELD_META[field].hint || FIELD_META[field].question)}</small></div>`).join("")}</div><div class="profile-form-actions"><span data-profile-error></span><button class="btn btn-primary" type="button">保存本模块</button></div>`;
    panel.querySelector("button").addEventListener("click", async () => {
      try {
        setError(panel);
        const patch = Object.fromEntries(section.fields.map((field) => [field, readField(panel, field)]));
        const confirmed = new Set(profile.confirmed_fields || []);
        const skipped = new Set(profile.skipped_fields || []);
        section.fields.forEach((field) => {
          if (patch[field] == null) { skipped.add(field); confirmed.delete(field); }
          else { confirmed.add(field); skipped.delete(field); }
        });
        patch.confirmed_fields = [...confirmed];
        patch.skipped_fields = [...skipped];
        const saved = await api.patchUserProfile(patch);
        notify("本模块已保存到 SQLite。");
        renderProfilePage(container, saved, notify);
      } catch (error) {
        setError(panel, error.message);
      }
    });
    sections.appendChild(panel);
  });

  container.querySelector("[data-profile-restart]").addEventListener("click", async () => {
    await api.patchUserProfile({ onboarding_completed: false, confirmed_fields: [], skipped_fields: [] });
    localStorage.setItem(STEP_KEY, "0");
    openProfileOnboarding(notify);
  });
  container.querySelector("[data-profile-clear]").addEventListener("click", async () => {
    if (!window.confirm("确认清空用户画像？清空后会再次触发首次建档。")) return;
    await api.deleteUserProfile();
    localStorage.removeItem(STEP_KEY);
    notify("用户画像已清空。");
    openProfileOnboarding(notify);
    mountProfilePage(container, notify);
  });
}

export async function maybeStartProfileOnboarding(notify = () => {}) {
  try {
    const status = await api.userProfileStatus();
    if (status.action_required === "profile_onboarding_required") {
      await openProfileOnboarding(notify);
    }
  } catch (error) {
    notify(error.message);
  }
}

export async function openProfileOnboarding(notify = () => {}) {
  const root = document.querySelector("#modalRoot");
  if (!root) return;
  const envelope = await api.userProfile();
  let profile = envelope.profile || {};
  let step = Math.min(Number(localStorage.getItem(STEP_KEY) || 0), STEPS.length);
  let confirmed = new Set(profile.confirmed_fields || []);
  let skipped = new Set(profile.skipped_fields || []);

  root.innerHTML = `<div class="profile-onboarding-backdrop"><section class="profile-onboarding" role="dialog" aria-modal="true" aria-label="首次用户画像建档"></section></div>`;
  const dialog = root.querySelector(".profile-onboarding");

  const close = () => { root.innerHTML = ""; };
  const render = () => {
    localStorage.setItem(STEP_KEY, String(step));
    if (step >= STEPS.length) {
      const allFields = STEPS.flatMap((item) => Array.isArray(item) ? item : [item]);
      const answered = allFields.filter((field) => profile[field] != null).length;
      dialog.innerHTML = `<div class="profile-progress"><span>画像摘要确认</span><strong>${answered}/${allFields.length}</strong><i style="width:100%"></i></div><h2>画像已整理，请确认保存</h2><p>未填写项保持为空，不会被填成 0。后续可以在“用户画像”栏目分模块修改。</p><div class="onboarding-summary">${profileCard("投资目标", text(profile.investment_goal))}${profileCard("投资期限", profile.investment_horizon_months == null ? "未填写" : `${profile.investment_horizon_months} 个月`)}${profileCard("可投资资金", money(profile.available_investment_funds_cny))}${profileCard("最大亏损", percent(profile.max_acceptable_loss_ratio))}</div><p class="profile-inline-error" data-profile-error></p><div class="onboarding-buttons"><button class="btn" data-back>上一步</button><button class="btn btn-primary" data-confirm>确认并完成建档</button></div>`;
      dialog.querySelector("[data-back]").onclick = () => { step -= 1; render(); };
      dialog.querySelector("[data-confirm]").onclick = async () => {
        try {
          const saved = await api.patchUserProfile({ onboarding_completed: true, confirmed_fields: [...confirmed], skipped_fields: [...skipped] });
          profile = saved.profile;
          localStorage.removeItem(STEP_KEY);
          close();
          notify("首次画像建档已完成并保存到 SQLite。");
        } catch (error) { setError(dialog, error.message); }
      };
      return;
    }
    const fields = Array.isArray(STEPS[step]) ? STEPS[step] : [STEPS[step]];
    const field = fields[0];
    const meta = FIELD_META[field];
    dialog.innerHTML = `<div class="profile-progress"><span>首次画像建档</span><strong>${step + 1}/${STEPS.length}</strong><i style="width:${((step + 1) / STEPS.length) * 100}%"></i></div><p class="profile-kicker">${esc(meta.label)}</p><h2>${esc(meta.question)}</h2><p>${esc(meta.hint || "可以跳过，缺失值会保持为空。")}</p><div class="onboarding-control">${fields.map((name) => inputMarkup(name, profile[name], fields.length > 1)).join("")}</div><p class="profile-inline-error" data-profile-error></p><div class="onboarding-buttons"><button class="btn" data-back${step === 0 ? " disabled" : ""}>上一步</button><button class="btn" data-exit>保存退出</button><button class="btn" data-skip>跳过</button><button class="btn btn-primary" data-next>保存并继续</button></div>`;
    dialog.querySelector("[data-back]").onclick = () => { step = Math.max(0, step - 1); render(); };
    dialog.querySelector("[data-exit]").onclick = close;
    dialog.querySelector("[data-skip]").onclick = () => save(true);
    dialog.querySelector("[data-next]").onclick = () => save(false);

    async function save(isSkip) {
      try {
        setError(dialog);
        const patch = {};
        fields.forEach((name) => {
          const value = isSkip ? null : readField(dialog, name);
          patch[name] = value;
          if (isSkip || value == null) { skipped.add(name); confirmed.delete(name); }
          else { confirmed.add(name); skipped.delete(name); }
        });
        const saved = await api.patchUserProfile({ ...patch, confirmed_fields: [...confirmed], skipped_fields: [...skipped], onboarding_completed: false });
        profile = saved.profile;
        step += 1;
        render();
      } catch (error) { setError(dialog, error.message); }
    }
  };
  render();
}
