{
  description = "Open RTL synthesis framework and tools";
  nixConfig.bash-prompt = "[nix(openXC7)] ";

  # Nixpkgs / NixOS version to use.
  inputs.nixpkgs.url = "nixpkgs/nixos-unstable";
  inputs.flake-utils.url = "github:numtide/flake-utils";
  outputs = { self, nixpkgs, flake-utils, ... }:
    let

      # to work with older version of flakes
      lastModifiedDate =
        self.lastModifiedDate or self.lastModified or "19700101";

      # Generate a user-friendly version number.
      version = builtins.substring 0 8 lastModifiedDate;

      # System types to support.
      supportedSystems =
        [ "x86_64-linux" "x86_64-darwin" "aarch64-linux" "aarch64-darwin" ];

      # Helper function to generate an attrset '{ x86_64-linux = f "x86_64-linux"; ... }'.
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;

      # Nixpkgs instantiated for supported system types.
      nixpkgsFor = forAllSystems (system: import nixpkgs { inherit system; });

      # The dies the manifest needs, each once, with the prjxray-db family
      # it lives in: one chipdb per die (xc7a35t parts route on the
      # xc7a50t one). The rule is pack/families.py's die_of -- the device
      # prefix of the part name, through the aliases of prjxray-db's
      # mapping/devices.yaml -- and this is its only other copy.
      dieAliases = { xc7a35t = "xc7a50t"; xc7s75 = "xc7s100"; xc7z035 = "xc7z045"; };
      dieOf = part:
        let device = builtins.head
          (builtins.match "(xc7(a|k|v|vx)[0-9]+t|xc7[sz][0-9]+).*" part);
        in dieAliases.${device} or device;
      manifest = builtins.fromJSON (builtins.readFile ./chipdb-parts.json);
      manifestDies = nixpkgs.lib.unique (builtins.concatMap
        (family: map (part: { inherit family; die = dieOf part; })
          manifest.${family})
        (builtins.attrNames manifest));

      # Toolchain shell, parameterized: `withFpgaAssembler = false` is the
      # packaging profile (devShells.<system>.pack) — openxc7-pack.py never
      # uses fpga-assembler, and skipping it avoids evaluating its flake
      # (builtins.getFlake github:lromor/...) on hosts whose GitHub egress is
      # unreliable (e.g. the build server) and shortens CI.
      mkToolShell = system: withFpgaAssembler:
        nixpkgsFor.${system}.mkShell {
          buildInputs = (with self.packages.${system}; [
            fasm
            prjxray
            nextpnr-xilinx
            # disabled, see above
            # yosys-synlig
          ]) ++ (with nixpkgsFor.${system}; [
            yosys
            openfpgaloader
            python312Packages.pyyaml
            python312Packages.textx
            python312Packages.simplejson
            python312Packages.intervaltree
          ])
          # fpga-assembler (gated above), ghdl and yosys-ghdl are not available on
          # aarch64-darwin; keep them Linux-only so the macOS devShell still resolves.
          ++ nixpkgsFor.${system}.lib.optionals nixpkgsFor.${system}.stdenv.isLinux (
            (nixpkgsFor.${system}.lib.optionals withFpgaAssembler
              (with self.packages.${system}; [ fpga-assembler ]))
            ++ (with nixpkgsFor.${system}; [ ghdl yosys-ghdl ])
          );

          shellHook =
            let mypkgs  = self.packages.${system};
                nixpkgs = nixpkgsFor.${system};
                pyPkgPath = "/lib/python3.12/site-packages/:";
            in nixpkgs.lib.concatStrings [
              "export NEXTPNR_XILINX_DIR=" mypkgs.nextpnr-xilinx.outPath "\n"
              # the generator of the chipdb files, in the nextpnr source tree
              # (pack/chipdb.py runs it once per die of the manifest)
              "export NEXTPNR_XILINX_CHIPDB_GEN=" mypkgs.nextpnr-xilinx.chipdbGenerator "\n"
              "export PRJXRAY_DB_DIR=" mypkgs.nextpnr-xilinx.outPath "/share/nextpnr/external/prjxray-db\n"
              "export PRJXRAY_PYTHON_DIR=" mypkgs.prjxray.outPath "/usr/share/python3/\n"
              ''export PYTHONPATH=''$PYTHONPATH:''$PRJXRAY_PYTHON_DIR:''
                mypkgs.fasm.outPath pyPkgPath
                nixpkgs.python312Packages.textx.outPath pyPkgPath
                nixpkgs.python312Packages.arpeggio.outPath pyPkgPath
                nixpkgs.python312Packages.pyyaml.outPath pyPkgPath
                nixpkgs.python312Packages.simplejson.outPath pyPkgPath
                nixpkgs.python312Packages.intervaltree.outPath pyPkgPath
                nixpkgs.python312Packages.sortedcontainers.outPath pyPkgPath
                "\n"
            ];
        };
    in {
      # Provide some binary packages for selected system types.
      packages = forAllSystems (system:
        let
          pkgs = nixpkgsFor.${system};
          inherit (pkgs) lib callPackage stdenv fetchgit fetchFromGitHub;
        in rec {
          prjxray-db = callPackage ./nix/prjxray-db.nix { };

          nextpnr-xilinx = callPackage ./nix/nextpnr-xilinx.nix {
            inherit prjxray-db;
          };

          prjxray = callPackage ./nix/prjxray.nix { };

          fasm = with pkgs;
            with python3Packages;
            callPackage ./nix/fasm {
              # NOTE(jleightcap): calling this package here is clucky.
              # contorted structure here to make the `nix/fasm` directory be
              # drop-in to upstream python-modules in nixpkgs.
              inherit buildPythonPackage pythonOlder textx cython fetchpatch jre_headless antlr4_9;
            };

          # nextpnr-xilinx-chipdb.<die>: the chipdb file of every die of the
          # manifest, as a store path (the packer and CI generate their own
          # with pack/chipdb.py, from the same generator and bbasm).
          nextpnr-xilinx-chipdb = builtins.listToAttrs (map (entry: {
            name = entry.die;
            value = callPackage ./nix/nextpnr-xilinx-chipdb.nix {
              inherit (entry) die family;
              inherit nextpnr-xilinx prjxray-db;
            };
          }) manifestDies);

          # disable yosys-synlig for now: synlig is not very good and it does not compile with recent yosys
          # yosys-synlig = callPackage ./nix/yosys-synlig.nix { };
        } // lib.optionalAttrs stdenv.isLinux {
          # fpga-assembler is gated to Linux: its upstream flake input
          # (github:lromor/fpga-assembler) does not evaluate on darwin and would
          # otherwise abort `nix develop` / `nix flake show` on macOS. On macOS the
          # openXC7 flow uses prjxray's xc7frames2bit instead.
          fpga-assembler = (builtins.getFlake "github:lromor/fpga-assembler/6ff89a2d53edc9d74a402c28096450473b67de13").packages.${system}.default;
        } // lib.optionalAttrs (system == "x86_64-linux") {
          # Windows tools tree, cross-compiled from x86_64-linux with
          # pkgsCross.mingwW64. CI injects the chipdb artifact before packaging.
          # Build: nix build .#openxc7-windows-amd64-tools. See nix/windows/.
          openxc7-windows-amd64-tools = import ./nix/windows {
            inherit pkgs lib;
            inherit (self.packages.${system})
              nextpnr-xilinx prjxray fasm;
          };
        });

      # contains a mutually consistent set of packages for a full toolchain using nextpnr-xilinx.
      devShell = forAllSystems (system: mkToolShell system true);

      # `nix develop .#pack` — same shell without fpga-assembler (packaging).
      devShells = forAllSystems (system: {
        pack = mkToolShell system false;
      });

      # dockerTools.buildImage targets Linux container images; expose it only on
      # Linux systems so the flake still evaluates (`nix flake show`) on macOS.
      dockerImage = nixpkgs.lib.genAttrs
        (builtins.filter (s: nixpkgs.lib.hasSuffix "-linux" s) supportedSystems)
        (system:
        let
          pkgs = nixpkgsFor.${system};
          mypkgs = self.packages.${system};
          # one chipdb-<die>.bin per die of the manifest, in one directory
          chipdb = pkgs.symlinkJoin {
            name = "nextpnr-xilinx-chipdb";
            paths = builtins.attrValues mypkgs.nextpnr-xilinx-chipdb;
          };
          pyPkgPath = "/lib/python3.10/site-packages/:";
        in
        pkgs.dockerTools.buildImage {
          name = "openxc7-docker";
          copyToRoot = pkgs.buildEnv {
            name = "image-root";
            paths = self.devShell.${system}.buildInputs ++ (with pkgs; [
              bashInteractive
              findutils
              gnused
              gnugrep
              coreutils
              gnumake
              python312
            ]) ++ [ chipdb ];
            pathsToLink = [ "/bin" ] ++ (with pkgs.dockerTools; [
              usrBinEnv
              binSh
            ]);
          };

          runAsRoot = pkgs.lib.concatStrings [ ''
            #!${pkgs.runtimeShell}
            mkdir -p /work
            cat > /bin/devshell <<EOF
            #!${pkgs.runtimeShell}
            '' self.devShell.${system}.shellHook "\n"
            "export PRJXRAY_DB_DIR=" mypkgs.nextpnr-xilinx.outPath "/share/nextpnr/external/prjxray-db\n"
            "export PRJXRAY_PYTHON_DIR=" mypkgs.prjxray.outPath "/usr/share/python3/\n"
            ''export PYTHONPATH=\''$PYTHONPATH:\''$PRJXRAY_PYTHON_DIR:''
              pkgs.python312Packages.textx.outPath pyPkgPath
              pkgs.python312Packages.pyyaml.outPath pyPkgPath
              pkgs.python312Packages.simplejson.outPath pyPkgPath
              pkgs.python312Packages.intervaltree.outPath pyPkgPath
              pkgs.python312Packages.arpeggio.outPath pyPkgPath
              pkgs.python312Packages.setuptools.outPath pyPkgPath
              pkgs.python312Packages.future.outPath pyPkgPath
              pkgs.python312Packages.sortedcontainers.outPath pyPkgPath
              mypkgs.fasm.outPath "/lib/python3.12/site-packages/"
              "\n"
            "export NEXTPNR_XILINX_DIR=" mypkgs.nextpnr-xilinx.outPath "\n"
            # chipdb-<die>.bin of every die of the manifest
            "export CHIPDB_DIR="         chipdb.outPath "\n"
            "\nexec ${pkgs.bashInteractive}/bin/bash\n"
            ''EOF
            chmod 755 /bin/devshell
          ''];

          config = {
            Cmd = [ "/bin/devshell" ];
            WorkingDir = "/work";
            Volumes = { "/work" = { }; };
          };
        }
      );
    };
}
