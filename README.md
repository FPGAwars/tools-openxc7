# tools-openxc7

> **Note:** Please **do not** open issues in this repository.
> For any questions, discussions, or bug reports, use the [main Apio repository](https://github.com/FPGAwars/apio).

Apio package with selected binaries from the [openXC7 project](https://github.com/openxc7)  

## Building the toolchain (For developers)

The current process for building the toolchain is manual, and only for 
Linux

Follow theses steps:

1. Install [Nix](https://nixos.org/download/#download-nix)
2. Clone this repo
3. From the repo's home folder execute `nix develop`
    * The first time it will take around 20 minutos to finish
    * All the tools will be built
    * After that, you will see the prompt: `[nix(openXC7)] `
    * Next execution of `nix develop` will take seconds
4. From the nix environment execute `./openxc7-pack.py`

## License

The Apio project itself is licensed under the GNU General Public License version 3.0 (GPL-3.0).
Pre-built packages may include third-party tools and components, which are subject to their
respective license terms.
