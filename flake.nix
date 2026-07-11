{
  description = "TiMOTION TC15S standing desk BLE controller";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f:
        nixpkgs.lib.genAttrs systems
          (system: f nixpkgs.legacyPackages.${system});

      mkDeskServer = pkgs: pkgs.python3Packages.buildPythonApplication {
        pname = "timotion-tc15s-ble";
        version = "0.1.0";
        format = "pyproject";

        src = ./.;

        build-system = [ pkgs.python3Packages.setuptools ];

        dependencies = with pkgs.python3Packages; [
          pyserial
          aiohttp
          aiohttp-cors
          pyyaml
        ];

        meta.mainProgram = "desk-server";
      };
    in
    {
      packages = forAllSystems (pkgs: {
        default = mkDeskServer pkgs;
      });

      nixosModules.default = { config, lib, pkgs, ... }:
        let
          cfg = config.services.timotion;
          desk-server = mkDeskServer pkgs;
        in
        {
          options.services.timotion = {
            enable = lib.mkEnableOption "TiMOTION desk BLE service";

            serialPort = lib.mkOption {
              type = lib.types.str;
              default = "/dev/ttyDONGLE";
              description = "Serial port for the ATM dongle.";
            };

            httpPort = lib.mkOption {
              type = lib.types.port;
              default = 8741;
              description = "HTTP API listen port.";
            };

            httpHost = lib.mkOption {
              type = lib.types.str;
              default = "0.0.0.0";
              description = "HTTP API bind address.";
            };

            deskName = lib.mkOption {
              type = lib.types.str;
              description = "BLE device name of the desk (from setup_dongle.py).";
            };

            openFirewall = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "Whether to open the HTTP port in the firewall.";
            };

            uhubctl = {
              enable = lib.mkEnableOption "POST /power-cycle endpoint via uhubctl";

              location = lib.mkOption {
                type = lib.types.str;
                description = ''
                  USB hub location the dongle is plugged into (uhubctl -l),
                  e.g. "1-1" or a hub VID:PID. Find it with `uhubctl`.
                '';
              };

              port = lib.mkOption {
                type = lib.types.int;
                description = "Hub port number the dongle is on (uhubctl -p).";
              };

              autoThreshold = lib.mkOption {
                type = lib.types.int;
                default = 5;
                description = ''
                  Auto power-cycle the port after this many consecutive
                  reconnect failures.
                '';
              };
            };
          };

          config = lib.mkIf cfg.enable {
            services.udev.extraRules = ''
              SUBSYSTEM=="tty", ATTRS{idVendor}=="1915", ATTRS{idProduct}=="521a", SYMLINK+="ttyDONGLE", MODE="0666"
              SUBSYSTEM=="usb", ATTR{idVendor}=="1915", ATTR{idProduct}=="521a", MODE="0666"
            '';

            systemd.services.timotion = {
              description = "TiMOTION Desk BLE Service";
              after = [ "network.target" ];
              wantedBy = [ "multi-user.target" ];

              environment = {
                SERIAL_PORT = cfg.serialPort;
                HTTP_PORT = toString cfg.httpPort;
                HTTP_HOST = cfg.httpHost;
                DESK_NAME = cfg.deskName;
              } // lib.optionalAttrs cfg.uhubctl.enable {
                UHUBCTL_PATH = "${pkgs.uhubctl}/bin/uhubctl";
                UHUBCTL_LOCATION = cfg.uhubctl.location;
                UHUBCTL_PORT = toString cfg.uhubctl.port;
                UHUBCTL_AUTO_THRESHOLD = toString cfg.uhubctl.autoThreshold;
              };

              serviceConfig = {
                ExecStart = "${desk-server}/bin/desk-server";
                Restart = "always";
                RestartSec = 5;
                SupplementaryGroups = [ "dialout" ];

                # Hardening
                ProtectSystem = "strict";
                PrivateTmp = true;
                NoNewPrivileges = true;
                DeviceAllow = [
                  "/dev/ttyDONGLE rw"
                  "/dev/bus/usb/* rw"
                ];
                # uhubctl 透過 libusb 對 hub 下 control transfer 切換 port 電源，
                # NoNewPrivileges + ProtectSystem=strict 下需要 CAP_SYS_RAWIO。
                AmbientCapabilities =
                  lib.mkIf cfg.uhubctl.enable [ "CAP_SYS_RAWIO" ];
              };
            };

            networking.firewall.allowedTCPPorts =
              lib.mkIf cfg.openFirewall [ cfg.httpPort ];
          };
        };
    };
}
