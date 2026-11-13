// Every colour, size and duration the dashboard uses. Components read CSS variables (applyTokens) or
// these constants (the fleet grid); nothing else names a colour or a pixel size.

export const color = {
  paper: "#EEF1F0",
  surface: "#FFFFFF",
  ink: "#172026",
  muted: "#56636C",
  rule: "#CCD4D6",
  sign: "#1F4E8C", // parking-sign blue: a fault the platform named
  ok: "#A9BDB6", // a bay whose scanner ran clean
  missed: "#6E7B83", // a field fault nobody named
  fallback: "#D99A1E", // ran the broken build and fell back on its own
  bricked: "#C2362B", // waited for a technician
  focus: "#1F4E8C",
} as const;

export const space = { 1: 4, 2: 8, 3: 12, 4: 16, 5: 24, 6: 32, 7: 48, 8: 72 } as const;
export const radius = { bay: 1, control: 4 } as const;
export const size = { hairline: 1, ring: 2, inset: 2, swatch: 12, bay: 9, bayGap: 2, siteGap: 6, statMin: 150, columnMin: 340 } as const;
export const font = {
  body: "'Barlow', system-ui, sans-serif",
  figure: "'Barlow Condensed', 'Barlow', system-ui, sans-serif",
  size: { small: 14, body: 17, lead: 21, h2: 28, h1: 52, figure: 40 },
  weight: { regular: 400, medium: 500, bold: 600 },
  leading: { tight: 1.05, body: 1.5 },
} as const;
export const layout = { measure: 66, page: 1160 } as const;
export const motion = { quick: 0.2, sweep: 0.9, shimmer: 1.4, ease: [0.25, 0.8, 0.25, 1] as const };
export const breakpoint = { narrow: 680 } as const; // mirrored in global.css: media queries cannot read variables

export function applyTokens(root: HTMLElement = document.documentElement): void {
  const px = (n: number) => `${n}px`;
  const vars: Record<string, string> = {
    "--font-body": font.body,
    "--font-figure": font.figure,
    "--measure": `${layout.measure}ch`,
    "--page": px(layout.page),
    "--leading-tight": String(font.leading.tight),
    "--leading-body": String(font.leading.body),
    "--shimmer": `${motion.shimmer}s`,
  };
  for (const [k, v] of Object.entries(font.size)) vars[`--text-${k}`] = px(v);
  for (const [k, v] of Object.entries(font.weight)) vars[`--weight-${k}`] = String(v);
  for (const [k, v] of Object.entries(color)) vars[`--${k}`] = v;
  for (const [k, v] of Object.entries(space)) vars[`--space-${k}`] = px(v);
  for (const [k, v] of Object.entries(size)) vars[`--${k}`] = px(v);
  for (const [k, v] of Object.entries(radius)) vars[`--radius-${k}`] = px(v);
  for (const [k, v] of Object.entries(vars)) root.style.setProperty(k, v);
}
