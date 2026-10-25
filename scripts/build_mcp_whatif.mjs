import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
await build({ configFile: path.join(repository, "apps/web/vite.mcp.config.mjs") });
const bundle = path.join(repository, ".mcp-whatif-build");
let html = fs.readFileSync(path.join(bundle, "mcp-whatif.html"), "utf8");
html = html.replace(/<script[^>]*src="([^"]+)"[^>]*><\/script>/g, (_, source) => {
  const script = fs.readFileSync(path.join(bundle, source.replace(/^\//, "")), "utf8");
  return `<script type="module">${script.replaceAll("</script", "<\\/script")}</script>`;
});
html = html.replace(/<link[^>]*href="([^"]+\.css)"[^>]*>/g, (_, source) => {
  const css = fs.readFileSync(path.join(bundle, source.replace(/^\//, "")), "utf8");
  return `<style>${css}</style>`;
});
const target = path.join(repository, "apps/api/src/personal_markets/remote_mcp/whatif_app.html");
fs.writeFileSync(target, html);
console.log(`Built self-contained What If MCP resource: ${fs.statSync(target).size} bytes`);
