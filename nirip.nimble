# Package
version       = "0.1.0"
author        = "andrew"
description   = "Declarative workspace orchestrator for Niri compositor"
license       = "MIT"
srcDir        = "src"
bin           = @["nirip"]

# Dependencies
requires "nim >= 2.0.0"
requires "results >= 0.4.0"
requires "chronos >= 4.0.0"
requires "jsony >= 1.1.0"
requires "toml_serialization >= 0.2.0"
requires "cligen >= 1.7.0"
requires "chronicles >= 0.10.0"
requires "nimri_ipc >= 0.1.0"
