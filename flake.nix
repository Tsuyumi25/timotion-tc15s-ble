{
  description = "TiMOTION TC15S standing desk BLE controller";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

      desk-server = pkgs.python3Packages.buildPythonApplication {
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
      packages.${system}.default = desk-server;

      nixosModules.default = { config, lib, pkgs, ... }:
        let
          cfg = config.services.timotion;
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
              };
            };

            networking.firewall.allowedTCPPorts =
              lib.mkIf cfg.openFirewall [ cfg.httpPort ];
          };
        };
    };
}
