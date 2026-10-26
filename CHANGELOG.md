# v1.0.0-rc1 — Caroline Bot 2.0

- Complete detection API for all seven original HuskyLens modes.
- UART and I2C communication; I2C bus can be externally managed.
- ID-filtered, learned-only, block-only and arrow-only queries.
- Learning, forgetting, custom names, screen text/clear, microSD photos/screenshots, model save/restore.
- Model Pro query and experimental 0x3C firmware handshake (not a version reader).
- Input validation; specific errors, timeout, checksum resync, BUSY retries, bounded memory/results.
- UART old API compatible: HuskyLens(tx=17, rx=16), ping(), set_algorithm(), get_blocks(), get_arrows().
- Offline emulator tests and examples.
- Not yet tested with physical HuskyLens 1 hardware. Text commands are firmware-dependent.
