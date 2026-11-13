import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { groupBySite, hours, share, tally } from "./format";
import { classify } from "./useReport";

describe("format", () => {
  it("groups devices into sites in order and counts states", () => {
    expect(groupBySite(["a", "a", "b"], "oxb")).toEqual([{ site: "a", states: ["o", "x"] }, { site: "b", states: ["b"] }]);
    expect(tally("oob")).toEqual({ o: 2, b: 1 });
    expect(share(0.999, 2)).toBe("99.90%");
    expect(hours(null)).toBe("not found");
    expect(hours(60)).toBe("2.5 days");
  });
});

describe("report states", () => {
  it("tells an empty report from a broken one, and reads the real one", () => {
    expect(classify(null).status).toBe("error");
    expect(classify({ runs: {} }).status).toBe("empty");
    const real = JSON.parse(readFileSync(join(__dirname, "../../../../reports/evaluation.json"), "utf8"));
    expect(classify(real).status).toBe("ready");
    expect(real.runs.platform.device_states.length).toBe(real.device_sites.length);
  });
});

describe("design tokens", () => {
  it("no component names its own colour or pixel size", () => {
    const files: string[] = [];
    const walk = (d: string) => readdirSync(d).forEach((f) => (statSync(join(d, f)).isDirectory() ? walk(join(d, f)) : files.push(join(d, f))));
    walk(join(__dirname, "../../features"));
    walk(join(__dirname, "../ui"));
    for (const f of files.filter((f) => f.endsWith(".tsx"))) {
      const src = readFileSync(f, "utf8");
      expect(src, f).not.toMatch(/#[0-9a-fA-F]{3,6}\b/);
      expect(src, f).not.toMatch(/\d+px/);
    }
  });
});
