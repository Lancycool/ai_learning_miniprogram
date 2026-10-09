"""Serve the compiled Taro H5 app with history fallback for direct page URLs."""
from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class HistoryFallbackHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        path = self.translate_path(self.path.split("?", 1)[0])
        if not Path(path).exists() and not self.path.startswith(("/js/", "/css/", "/chunk/")):
            self.path = "/index.html"
        return super().send_head()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the compiled Taro H5 app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "dist"
    if not (root / "index.html").exists():
        raise SystemExit("frontend/dist/index.html 不存在，请先执行 H5 构建")
    handler = lambda *items, **kwargs: HistoryFallbackHandler(*items, directory=str(root), **kwargs)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"H5 已启动：http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
