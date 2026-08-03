# udev/ — USB permissions for programming boards on Linux

On Linux the kernel creates the USB device node owned by `root`, so a normal
user cannot talk to a programming cable until a udev rule grants access.
Without it, `make prog` (or `apio upload`) fails with a permission error even
though everything else is installed correctly.

This affects **Linux only**. macOS has no udev, and Windows needs a driver
(typically WinUSB via Zadig) instead.

## What this file is

`99-openfpgaloader.rules` is a **verbatim copy** of the rules published by
openFPGALoader upstream, which is the tool that actually programs the board:

| | |
|---|---|
| Source | <https://github.com/trabucayre/openFPGALoader> |
| File | `99-openfpgaloader.rules` |
| Revision | `2e12478a6` (2025-09-03) |
| License | Apache-2.0 (the openFPGALoader project's) |

It is kept here purely for convenience: `openFPGALoader` ships inside
oss-cad-suite, but its rules file does not, so a user following the
standalone instructions has no way to obtain it. Refresh it from upstream
rather than editing it by hand, and update the revision above when you do.

It covers every USB id used by the Xilinx boards we support today —
`0403:6010` and `0403:6014` (FTDI), `09fb:6001` (Xilinx cable), `0d28:0204`
(CMSIS-DAP) and `2a19:1009` — plus many others.

## Installing it

Root is needed once, not on every use:

```bash
sudo cp udev/99-openfpgaloader.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Then unplug and replug the board. The rules use `TAG+="uaccess"`, which
grants access to the user of the active session on modern systemd distros,
and also set `GROUP="plugdev"` for older ones — on those, add yourself to
that group (`sudo usermod -aG plugdev $USER`) and log back in.

## What not to do

Running the programmer with `sudo` looks like it works and is a bad idea:
besides needing root to drive a cable, `sudo` resets the environment, so the
toolchain that `source start` (or apio) put on your `PATH` is no longer
visible and the command often fails for a second, confusing reason.
