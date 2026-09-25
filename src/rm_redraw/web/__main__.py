"""Start the small local replay utility."""

import argparse
from pathlib import Path

from .server import create_server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", type=Path, default=Path("artifacts/replay-workbench"))
    parser.add_argument("--import", dest="imports", type=Path, action="append", default=[])
    args = parser.parse_args()
    server = create_server(args.data, port=args.port)
    for path in args.imports:
        server.app.library.add(
            path.read_bytes(), provenance={"provider": "local-file", "path": str(path.resolve())}
        )
    print(f"Replay utility: http://127.0.0.1:{server.server_port}", flush=True)
    print(f"Local files: {args.data.resolve()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.app.jobs.close()


if __name__ == "__main__":
    main()
