"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(root, "frontend/office/js/app.js"), "utf8");
const api = fs.readFileSync(path.join(root, "frontend/office/js/api.js"), "utf8");
const profile = fs.readFileSync(path.join(root, "frontend/office/js/profile.js"), "utf8");
const css = fs.readFileSync(path.join(root, "frontend/office/css/office.css"), "utf8");

assert.match(app, /route:\s*"profile"/);
assert.match(app, /maybeStartProfileOnboarding/);
assert.match(app, /mountProfilePage/);

for (const method of [
  "userProfile",
  "userProfileStatus",
  "putUserProfile",
  "patchUserProfile",
  "deleteUserProfile",
]) {
  assert.match(api, new RegExp(`${method}:`));
}

for (const field of [
  "monthly_after_tax_income_cny",
  "income_stability",
  "dependents_count",
  "emergency_fund_cny",
  "investment_horizon_months",
  "max_acceptable_loss_ratio",
  "existing_positions",
  "investment_experience",
]) {
  assert.match(profile, new RegExp(field));
}

assert.match(profile, /保存退出/);
assert.match(profile, /跳过/);
assert.match(profile, /重新进行建档/);
assert.match(profile, /确认清空用户画像/);
assert.match(profile, /SQLite 是画像事实源/);
assert.match(profile, /localStorage\.setItem\(STEP_KEY/);
assert.doesNotMatch(profile, /localStorage\.setItem\([^,]+,\s*JSON\.stringify\(profile/);

assert.match(css, /\.profile-onboarding-backdrop/);
assert.match(css, /\.profile-form-grid/);

console.log("user profile Office integration tests passed");
