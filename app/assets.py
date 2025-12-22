DEFAULT_CSS = r"""
/* default.css (embedded)
   - transparent background
   - transparent border
   - safe for OBS browser source overlay
*/

:root {
  --bg: rgba(0, 0, 0, 0);
  --fg: rgba(255, 255, 255, 0.95);
  --border: rgba(255, 255, 255, 0.35);
  --muted: rgba(255, 255, 255, 0.6);

  --font-size: 28px;
  --line-height: 1.25;

  --item-gap: 8px;
  --item-padding-y: 10px;
  --item-padding-x: 14px;
  --item-radius: 10px;
  --item-border-width: 1px;

  --shadow: 0 0 0 rgba(0,0,0,0);
}

html, body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--fg);
  font-size: var(--font-size);
  line-height: var(--line-height);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", Arial, sans-serif;
}

a { color: inherit; text-decoration: none; }

.container {
  padding: 16px;
}

.title {
  font-weight: 700;
  margin-bottom: 12px;
  text-shadow: 0 2px 8px rgba(0,0,0,0.35);
}

.queue {
  display: flex;
  flex-direction: column;
  gap: var(--item-gap);
}

.item {
  border: var(--item-border-width) solid var(--border);
  border-radius: var(--item-radius);
  padding: var(--item-padding-y) var(--item-padding-x);
  background: rgba(0,0,0,0.08);
  box-shadow: var(--shadow);
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.index {
  font-weight: 800;
  min-width: 2.2em;
  opacity: 0.95;
}

.name {
  font-weight: 700;
}

.badge {
  margin-left: 10px;
  font-size: 0.75em;
  opacity: 0.9;
  padding: 3px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
}

.marked {
  border-color: rgba(255, 210, 64, 0.85);
  background: rgba(255, 210, 64, 0.12);
}

.full {
  color: var(--muted);
  border-style: dashed;
}

.hint {
  color: var(--muted);
  font-size: 0.85em;
  margin-top: 10px;
}
""".lstrip()


