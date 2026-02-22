MultiThread-Tools-Box
=====================

Layered project: `core/`, `cli/`, `gui/`, `common/`.

Usage (CLI):

```
BTM <command> [options]

Commands:
  download   -u URL -p PATH -t THREADS [-n NAME]
  duplicate  -p PATH -t THREADS [--similarity]
  monitor    [--interval SECONDS]
  rename     -p PATH -r RULES
  speedtest  [--duration SECONDS]
  image      -p PATH -o OUTPUT [--resize WxH] [--format FMT]
```

Run the CLI:

```
python -m cli.main ...
```

Requirements:
- Python 3.8+
- Standard library only for `core/` implementation
- `argparse` for CLI
- `tkinter` for GUI
- `threading` + `concurrent.futures` for multithreading

This repository provides basic, extensible implementations and uses callback-based
progress reporting. Image resize/convert operations require Pillow; otherwise the
`image` command will perform safe copy or report the missing capability.
