"""Allow ``python -m csvftps ...`` as an alias for the CLI."""

from csvftps.cli import main

raise SystemExit(main())
