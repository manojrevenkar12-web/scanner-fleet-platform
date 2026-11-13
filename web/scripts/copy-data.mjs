// The dashboard shows the evaluation's own files; nothing is typed in by hand.
import { copyFileSync, mkdirSync } from "node:fs";
mkdirSync("public/data", { recursive: true });
for (const f of ["evaluation.json", "heldout.json"]) copyFileSync(`../reports/${f}`, `public/data/${f}`);
console.log("copied reports into public/data");
